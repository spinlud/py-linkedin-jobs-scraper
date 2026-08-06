# Authenticating without harvesting cookies: what was built, and how much of it is proven

Written 2026-08-05, on branch `chore/v6.0.0-linkedin-dom-update`. Companion to
[`li-at-cookie-revocation.md`](li-at-cookie-revocation.md), which covers why headless sessions
were dying in the first place. This document covers what replaced the hand-harvested `li_at`
cookie, and is deliberate about separating what was measured from what is merely believed.

## How to read the claims

Every non-obvious statement below carries one of these:

- **[verified]** — measured, repeated or deterministic enough that a single measurement settles
  it, and the exact numbers are in the *Runs* table.
- **[observed]** — seen happen, once, without controlling for the alternatives. LinkedIn is a
  live remote system behind bot management; one observation is evidence, not proof.
- **[inferred]** — a conclusion drawn from several observations plus how the thing plainly
  works. Sound, but not directly tested.
- **[unproven]** — stated because it matters, and explicitly not established. Some of these are
  inherited from earlier work and never re-checked; they are marked as such.

One asymmetry governs almost everything here, and it is the same one that got the HTTP session
probe deleted: **an acceptance proves much more than a refusal.** When LinkedIn mints a session
cookie, it accepted the credential — there is no plausible other explanation. When it redirects
to `/login`, that may be the credential, or bot management, or throttling, or an interstitial.
So the "session issued" rows below are strong and the "refused" rows are weak, and the
conclusion drawn from them is only as strong as its weakest link.

## The short version

LinkedIn issues, to a sign in that ticked "Keep me logged in", a **remember me credential**
that can be asked for a fresh session cookie at any time. It is two cookies, `li_rm` and
`bcookie`, and it replaces `LI_AT_COOKIE` rather than complementing it: in every experiment
below **no `li_at` was ever injected** and the scraper still authenticated **[verified]**.

That gives one mechanism covering both environments the scraper runs in:

- **A machine with a display** signs in once into a Chrome profile, and the profile holds the
  credential. `interactive_login=True` does the sign in from `run()`.
- **A machine without one** — EC2, a container, CI — gets the same two values as environment
  variables, `LI_RM_COOKIE` and `LI_BCOOKIE`.

`LI_AT_COOKIE` still works and is now the documented fallback, for accounts that cannot produce
a remember me cookie.

## What the credential actually is

Five combinations were injected into **pristine Chrome profiles that had never signed in**,
each a fresh directory, then `/feed/` was requested and the jar checked for a session cookie.
The cookies came out of a profile that had signed in by hand.

| Injected | Result | |
| --- | --- | --- |
| `li_rm` | refused, `302 → /login` | **[observed]**, once |
| `li_rm` + `bscookie` | refused, `302 → /login` | **[observed]**, once |
| `li_rm` + `bcookie` | **session issued** | **[verified]** |
| `li_rm` + `bcookie` + `bscookie` | **session issued** | **[observed]**, once |
| `li_rm` + `bcookie` + `bscookie` + `liap` + `JSESSIONID` + `lidc` + `li_mc` | **session issued** | **[observed]**, once |

**The credential is `li_rm` bound to the `bcookie` it was issued to** **[inferred]** — from
those five points plus the fact that `bcookie` is, by its own value (`"v=2&<uuid>"`), a browser
identifier. The two refusals are the weak half of that inference; what makes it usable anyway
is that the accepting combination has since been exercised repeatedly, including by the
project's own test suite.

`bscookie` is **not** part of it and cannot stand in for `bcookie` **[observed]** — it is the
one asymmetry in the table that would be worth a second run before anybody relies on it.

Note what is *not* claimed: that nothing else is required. Everything in that table ran on one
laptop, from one IP, with one User-Agent. See *What is not proven*.

### Cookie attributes, as LinkedIn issues them

Read directly out of a signed-in profile's jar **[verified]**:

| Cookie | Domain | HttpOnly | Expiry attribute |
| --- | --- | --- | --- |
| `li_at` | `.www.linkedin.com` | yes | +1 year |
| `li_rm` | `.www.linkedin.com` | yes | +1 year |
| `bcookie` | `.linkedin.com` | **no** | +1 year |
| `bscookie` | `.www.linkedin.com` | yes | +1 year |

Two practical consequences:

- `bcookie` sits on a **different domain** from the other two, which is why
  `set_remember_me_cookies` injects them with different domains. Injecting either on the wrong
  one leaves the browser unauthenticated.
- Both halves are **readable** from the developer tools cookie panel, `li_rm` included:
  `HttpOnly` hides a cookie from `document.cookie`, not from that panel. Being readable turned
  out not to be enough — see *Where the pair has to come from*, which corrects an earlier
  version of this document that told people to copy them from their browser.

### `bcookie`'s value contains literal double quotes, and they turn out not to matter

The value is `"v=2&<uuid>"`, quote characters included, 42 characters **[verified]**. The
obvious worry is a user stripping them on the way into a shell variable. Tested: with the two
quotes removed, 40 characters, LinkedIn **still issued a session** and the run scraped 2 of 2
jobs **[observed]**, once each way. So this is one less thing to get wrong, though a
copy-paste that keeps them is still the safer instruction.

## Where the pair has to come from

**A pair copied out of an everyday Chrome does not work.** This was measured after the fact and
it falsifies a claim an earlier version of this document made with a **[verified]** label, so it
is worth being exact about what was compared.

Same LinkedIn account, same machine, same IP, same Chrome binary, two remember me credentials:

| Issued to | Redeemed from a pristine profile | Attempts |
| --- | --- | --- |
| a Chrome launched by this project's `build_driver`, via the login command | **session issued** | ~10, all successful |
| the maintainer's everyday Chrome, signed in by hand minutes earlier | **refused**, `302 → /login` | 4, all refused |

The four refusals were `li_rm` + `bcookie`; plus `liap`; plus `bscookie`; and plus `bscookie`,
`liap` and `JSESSIONID` together — every cookie in that browser's jar that could plausibly carry
a device identity. All values were checked for length against the sizes the cookie panel
reports, so none was truncated, and `bcookie` was tried both with and without the double quotes
that are part of its value.

Ruled out **[verified]**:

- Truncation, or a copy-paste error — `li_rm` was 342 characters in both cases, matching the
  panel's reported size exactly.
- The quotes around `bcookie`'s value.
- Anything account-level: 2FA, an account flag, an expired credential. The working credential
  and the refused one belong to **the same account**.
- Device Bound Session Credentials. Chrome's *Device bound sessions* panel was empty for that
  browser, so the session was not cryptographically bound to a device key.
- Any of the cookies listed above.

**The mechanism is unknown** **[unproven]**. Whatever distinguishes the two credentials is not a
cookie that can be identified and moved. The hypothesis worth testing next is that LinkedIn
issues a *portable* remember me token to a browser profile with no history and a
*device-bound* one to an established browser — which would mean the login command works
precisely because the profile it creates is disposable. That is speculation; it has not been
measured, and nothing here should be read as knowing why.

**The practical rule, which is what matters:** get the pair from
`python -m linkedin_jobs_scraper.login`, which prints it. Do not tell users to read it out of
their own browser.

This also weakens, without contradicting, the *What the credential actually is* table above: the
minimal set was established for a credential issued to a driver-launched Chrome, and it may not
be minimal — or even sufficient — for one issued anywhere else.

## What was built

**New configuration.** `Config.LI_RM_COOKIE` and `Config.LI_BCOOKIE`, read from the
environment at import time like `LI_AT_COOKIE` — so setting `os.environ` after importing the
package still has no effect.

**`utils/session.py`** was generalised from one cookie to several: `get_cookie` / `set_cookie`
underneath, `get_session_cookie` / `set_session_cookie` as thin wrappers over them, and
`set_remember_me_cookies` injecting the pair with the right domain and an expiry each.
`probe_session_cookie` and its supporting machinery were **deleted** — nothing called it, and
its correct use needed a paragraph of caveats every time.

**`AuthenticatedStrategy.__authenticate`** replaced the inline cookie-setting block and is now
the single place a session is obtained. It prefers having one *issued*: if the jar holds no
`li_rm` and a pair was supplied, it injects it; if a `li_rm` is present from either source, it
asks LinkedIn for a session; only failing that does it fall back to injecting `LI_AT_COOKIE`.
A supplied pair never overwrites a profile's own, because `li_rm` is bound to the `bcookie`
next to it and mixing halves would break both **[inferred]**.

**`AuthenticatedStrategy.__open_results`** replaced the "open the search URL, then assert the
cookie is still there" sequence. A refusal is no longer fatal on sight: the session is dropped
from the jar, `__authenticate` runs again, and the page is retried once. This is what lets a
freshly supplied credential win against a profile holding a retired one — the jar is consulted
first, so without it the stale cookie kept winning and the run died with the good cookie never
tried. `InvalidCookieException` is now raised only when the retry ends with no session at all;
a session that renders no results skips the location instead, because throttling looks exactly
like that.

**`interactive_login`** on the constructor, off by default, requiring `user_data_dir`. When on,
`run()` calls `login.ensure_session` before submitting any query — Chrome locks a profile
directory, so the sign in has to be over before a worker opens a browser on it.
`login.has_credentials` spends one short-lived headless browser deciding whether a sign in is
needed at all, which is cheaper than opening a window somebody then has to close.

**`login.py`** grew `sign_in` / `has_credentials` / `ensure_session` as reusable functions, and
the command now prints the `LI_RM_COOKIE` and `LI_BCOOKIE` values on success. Signing in on a
laptop is therefore also how a display-less host is provisioned.

**Docs.** The README's authentication section was rewritten to start from the user's question —
where does this run — rather than from the history of the bug. `CLAUDE.md` gained *Two
credentials, and they are not equivalent*.

## Runs

Every run headless, on Chrome 150 locally, against live LinkedIn, with one account's
credential. Job counts are `records / requested`.

| Run | Configuration | Result |
| --- | --- | --- |
| Remote mode | pair only, no profile, no `LI_AT_COOKIE` | 5/5, 0 failed, session minted |
| Remote mode | same, smaller limit | 3/3, 0 failed |
| Remote mode | same, `bcookie` with its quotes stripped | 2/2, 1 card render failure |
| Seed a profile | pair + fresh `user_data_dir` | 3/3, profile ends up holding `li_at` + `li_rm` + `bcookie` |
| Recover | `li_at` deleted from that profile, then run with a **completely empty environment** | 3/3, session reissued |
| Profile from an interactive sign in | `li_at` deleted, `li_rm` kept | 6/6, session reissued |
| Fallback | `LI_AT_COOKIE`, no profile | 3/3, 1 card render failure |
| Fallback, the trap | profile holding an invalid `li_at`, valid `LI_AT_COOKIE` supplied | 3/3, 1 card render failure |
| **Project test suite** (`pytest -q`, 2 queries, the second with `apply_link=True`) | **pair only** | **1 passed, 126.63s** |
| Interactive-login decision | `has_credentials` against a signed-in and an empty profile | `True` / `False`, no window opened on the signed-in one |

That is roughly ten sessions minted from a single `li_rm` over one afternoon, all successful.

## Facts that hold because of how Chrome works, not because of LinkedIn

**An injected cookie needs an expiry or it does not survive the browser closing**
**[verified]**. `driver.add_cookie` without one creates a session cookie, which Chrome discards
on exit. The first attempt at seeding a profile from the pair therefore left it holding `li_at`
and **no** `li_rm`: the session persisted, and the thing that renews the session did not. The
fix is `REMEMBER_COOKIE_MAX_AGE`, and it flipped the measurement — `li_rm` present after
seeding, and the recover-with-an-empty-environment run above then passed.

`bcookie` hid that bug by surviving anyway, because LinkedIn re-sends it with an expiry of its
own **[inferred]** — the value in the profile was the injected one, and it was still there
after a restart, which is hard to explain otherwise.

**A profile's cookie jar is loaded from disk at startup, so reading it after the first
navigation is safe** — unlike reading a cookie that has to *arrive* in a response, which is the
long-standing trap that `__wait_for_session` exists for.

**LinkedIn answers a structurally invalid `li_at` by clearing it** **[verified]**: a garbage
value seeded into a profile was gone from the jar after the next start and navigation. This is
worth knowing for anyone writing tests here — it means a garbage cookie **cannot** be used to
reproduce the other refusal signature, the one where the cookie is left in place.

## What is not proven

This is the part to read before promising anything to a user.

- **Nothing was tested from a second machine**, and this is now the biggest open risk rather
  than a formality. Every run above shares one IP, one operating system and one browser build.
  All that has been shown is that a pair travels between *Chrome profiles on one machine*.
  Carrying it to EC2 changes the IP, the platform in the User-Agent and the
  `Sec-CH-UA-Platform` hint at once, and *Where the pair has to come from* proves that
  something outside the cookies can make LinkedIn refuse a credential that looks complete. So
  whether the server mode works on an actual server is **[unproven]**. The next useful
  experiment is exactly that: export the pair to a remote host and run three jobs.
- **"It lasts a year" is the cookie's own expiry attribute, not a measurement** **[unproven]**.
  A server can retire a credential long before the value it wrote in the expiry field. All that
  is established is that this `li_rm` worked for ten uses across a few hours.
- **`li_rm` was never seen to rotate** **[observed]** — the value was identical after every
  experiment and the source profile kept working. Ten uses in one afternoon is not evidence
  about a year, and a rotation on some other trigger cannot be ruled out.
- **"Accounts with two factor authentication never receive `li_rm`"** is **[unproven]** and
  **inherited** from earlier work in this repo; it was not re-checked here. It is the entire
  justification for keeping `LI_AT_COOKIE`, so if it turns out to be wrong, that fallback has
  no remaining reason to exist.
- **The second refusal signature is handled but never exercised.** LinkedIn refuses in two
  ways: clearing the cookie, or leaving it in the jar and serving the logged out page.
  `__open_results` treats them identically, and only the first has been reproduced. The second
  needs a well-formed but genuinely retired cookie, which cannot be produced on demand.
- **Concurrency with the pair is untested** **[unproven]**. `max_workers` is forced to 1 only
  when `user_data_dir` is set. With the pair and no profile, N workers would each mint their own
  session from the same `li_rm` at the same moment. Nothing is known about how LinkedIn reacts
  to that; the README's existing advice of one worker in authenticated mode is the reason it has
  not bitten.
- **Shipping a seeded profile directory to another host** is **[unproven]** and probably a dead
  end from macOS, where Chrome encrypts the cookie jar with a key in the OS keychain. Moot now
  that the credential itself travels.

## Known noise, not a regression

Several runs above report `failed 1` alongside a complete set of records. That is
`__load_job_card` timing out on one card: the code increments `metrics.failed` and logs, but
does **not** emit an `ERROR` event, which is why the counters can read `failed 1, errors 0`
**[verified]** by reading the code and matching it to the runs. It predates this work, appears
intermittently, and its cause is not established.

## Do not

- **Do not reintroduce an HTTP pre-flight check** of any credential. A refusal from outside a
  browser is not a verdict; a previous version of that idea raised `InvalidCookieException` on a
  cookie that then drove a full run to `PASS`.
- **Do not present `LI_AT_COOKIE` as the normal way in.** Nothing can renew it, and it has been
  measured at roughly a hundred job loads before LinkedIn retires it.
- **Do not inject half a pair** over a profile's own, and do not assume `bscookie` will do
  instead of `bcookie`.
- **Do not make `interactive_login` default to `True`.** It waits up to ten minutes for a human
  and needs a display; as a default it would hang CI and every server.
- **Do not push to `master`.** `.github/workflows/ci.yml` publishes to PyPI on every push there.
