# `li_at` session loss during headless runs

Findings as of 2026-08-05. This replaces an earlier version of this document whose leading
hypothesis turned out to be wrong; the corrections are called out below so the same dead
ends are not explored twice.

What replaced the hand-harvested cookie is written up separately, with each claim marked by how
well it is established: [`session-credentials.md`](session-credentials.md).

## The problem as it was

A session cookie survived roughly **one** headless scraping run of 5–8 jobs. Every attempt
to finish an end-to-end verification cost a freshly harvested cookie, four in a row.

Two findings ended it. Suppressing the headless fingerprint took one cookie from 5–8 jobs to
roughly a hundred, and LinkedIn's remember me credential removed the cookie from the loop
altogether: it can be asked for a fresh session on every run, it lasts a year, and it works
both from a profile signed in by hand and from two environment variables on a host with no
display. Harvesting `li_at` is now the fallback for accounts that cannot produce that pair.

## The cause: the browser announced itself as headless

Chrome in `--headless=new` puts a `HeadlessChrome` token in the User-Agent, and the project
also passed `--enable-automation`, which sets `navigator.webdriver`. Both were measured, by
running Chrome with the project's own flags against a local HTTP server:

| Signal | Before | After |
| --- | --- | --- |
| `User-Agent` header and `navigator.userAgent` | `…HeadlessChrome/150.0.0.0…` | `…Chrome/150.0.0.0…` |
| `navigator.webdriver` | `true` | `false` |
| `sec-ch-ua` | `"Google Chrome";v="150"`, contradicting the User-Agent | agrees with the User-Agent |

Every authenticated request carried the first column. The fix is in
`utils/chrome_driver.py`: `excludeSwitches` drops `enable-automation`, and
`mask_headless_user_agent` rewrites the User-Agent through
`Network.setUserAgentOverride`, passing `userAgentMetadata` read from the browser so the
client hints keep agreeing with it.

Two details that cost time and are worth keeping:

- **`acceptLanguage` must not be passed** to `Network.setUserAgentOverride`. Chrome appends
  a second quality value to every entry, yielding `en-GB,en-US;q=0.9;q=0.9,…`. The
  `--lang` argument already produces a correct `Accept-Language`.
- **The override needs a secure context.** `navigator.userAgentData` is absent on the
  `data:,` page a driver starts on, so the masking runs right after the first navigation to
  LinkedIn. That first request is made before the session cookie is injected, so no
  authenticated request ever carries the headless token.

### The CDP override alone was not enough

`Network.setUserAgentOverride` applies to **one target**. The tab `__extract_apply_link`
opens is another one, it lands on a LinkedIn URL carrying the session cookie before being
redirected off site, and it announced itself as headless. The official pytest suite ended a
session on its second query — 27 jobs with `apply_link=True` — with the cookie cleared from
the jar.

The fix is `resolve_masked_user_agent`, which spends one short lived browser per process to
read `navigator.userAgent` — readable on the initial blank page, unlike
`navigator.userAgentData` — and passes the de-headlessed value as the `--user-agent` launch
flag, which every target inherits. Verified directly: a page that opens a second tab now has
both requests carrying the masked `User-Agent` with coherent `Sec-CH-UA`. The CDP path is
kept as a fallback for callers who supply their own `chrome_options`, where no flag can be
injected.

### Why commit `6520ae2` made things worse

That commit disabled a random User-Agent override with the note that it *"can cause the
session cookie to be invalidated earlier then expected"*. The list it drew from,
`utils/user_agent.py`, held Chrome 55–62 and Firefox 55 strings from 2017. Overriding a
Chrome 150 browser with a Chrome 55 User-Agent while `sec-ch-ua` still announced Chromium
150 produced a contradiction louder than the leak it was hiding. The module has been
deleted. The lesson is not "never touch the User-Agent" but "derive it from the browser and
keep every related signal consistent".

## Result

One cookie, six consecutive runs, no revocation and no manual step:

| Run | Records | Notes |
| --- | --- | --- |
| 1 | 8 | baseline |
| 2 | 25 | list grown past the ~12 rendered cards |
| 3 | 30 | pagination to `?start=25` |
| 4 | 25 | strict field validation, 0 violations |
| 5 | 10 | strict field validation, PASS |
| 6 | 12 | `apply_link=True`, PASS, every link an external ATS host |

Roughly 110 job detail loads on a session that previously died after 5–8, including one run
in the container on Chrome 151 under Linux.

The official pytest suite — two queries, the second 27 jobs with `apply_link=True` — then
passed **twice in a row** on one cookie after the apply-link tab leak was fixed, having
failed on that same suite before the fix. A third heavy run on that cookie, a couple of
hours and roughly 110 more job loads later, failed with `InvalidCookieException`.

So the honest summary of the cookie path is: **an order of magnitude more work per
harvested cookie, not an unlimited one.** A manually supplied `li_at` is a snapshot of a
credential nobody is refreshing, and it eventually runs out. That is the argument for the
persistent profile below, which does not run out — the same account kept scraping through a
profile in the very session where the hand-harvested cookie had stopped working.

## Corrections to the earlier hypotheses

- **The cookie is not bound to a device.** A plain `curl` carrying only `li_at`, with no
  `bcookie`, no `bscookie` and no `JSESSIONID`, is answered with the full authenticated
  page, and LinkedIn mints the device cookies itself. Presenting the session from an
  unknown browser is not what triggered anything.
- **`li_at` is not rotated out from under the scraper.** The value a browser held was
  compared against the value the scraper had been using: identical, while the browser
  stayed signed in.
- **`--disable-web-security` was inert.** Chrome ignores it unless `--user-data-dir` is
  also set, which the project did not do. It still had to go, because adding the
  persistent profile would have switched it on, and a disabled same-origin policy is
  detectable from the page.
- **`Network.enable` and `Page.setBypassCSP` were removed** as unnecessary CDP surface.
  `apply_link=True` was re-verified afterwards and still captures off-site links, so
  nothing depended on them.

## Only a browser can tell you whether a session is alive

A `HEAD` request to `/feed/` carrying just the cookie looks like an obvious pre-flight check.
It is not one, and the utility that did it has been **deleted** rather than left around to be
mistaken for an oracle.

It is asymmetric: a `200` means the session is live, but a refusal proves nothing. LinkedIn
sits behind Cloudflare bot management and refuses on the shape of the client as well as on the
session, and such a request is about as unlike a browser as it gets — one cookie out of a
dozen, no browser TLS fingerprint.

This bit once already: the probe reported a cookie dead, consistently, across eight attempts
over 140 seconds, with `302 → /uas/login`. The same cookie then drove a full headless run to
`PASS`. A first version of the pre-flight check raised `InvalidCookieException` on that
verdict, which would have aborted working runs.

LinkedIn refuses a session in two ways, and only one of them clears the cookie:

- `set-cookie: li_at=delete me; …; Max-Age=0` — the cookie is cleared.
- `302 → /uas/login?session_redirect=…` — the cookie is left in the jar and ignored.

`__open_results` treats them identically, because the jar is not evidence either way: it drops
whatever session the jar holds and authenticates once more before retrying the page. A
by-product worth knowing when writing tests: LinkedIn answers a **structurally invalid**
cookie with the first signature, so a garbage value cannot be used to reproduce the second.

## Telling failures apart

- `InvalidCookieException` — every credential available was refused and LinkedIn would not
  issue another. Aborts the run.
- `LinkedIn refused the session…` — a refusal that is about to be answered by authenticating
  again. Only fatal if it repeats.
- `Still no results after authenticating again` — LinkedIn accepted a session but rendered no
  list. Throttling looks exactly like this, so the location is skipped rather than the run
  aborted.
- `LinkedIn served the logged out page…` — from `__is_guest_page`. The cookie is in the jar
  and LinkedIn ignored it.
- `Results container .scaffold-layout__list never appeared` — authenticated, but the DOM
  changed. This is the one that means "go fix selectors".
- `Timeout on pagination: …` — now carries a `__describe_page` dump: ready state, whether
  the container and the guest markers are present, item count, title, URL and the first
  220 characters of visible text.

## When the session dies, the scraper recovers on its own

**No clicking is involved.** The expectation going in was that recovery would mean
automating LinkedIn's sign in page — clicking the remembered account, then answering the
consent interstitials that follow. It does not. A profile holding `li_rm` gets a **new
session cookie issued silently** on the next request to an authenticated route, with no
interaction and no UI to scrape. The account offered on the sign in page is the same
mechanism with a human in front of it.

This was verified by reproducing the revoked state exactly, which is worth knowing because
it makes the whole path testable on demand instead of only after a real revocation: open the
profile, `driver.delete_cookie('li_at')`, keep `li_rm`, navigate. End to end, with
`LI_AT_COOKIE` unset and only `user_data_dir` configured, the scraper recovered the session,
scraped 6 of 6 jobs with no errors, and emitted `SESSION_REFRESHED` carrying a cookie
different from the deleted one.

**Setup, once.** `python -m linkedin_jobs_scraper.login --user-data-dir <path>` opens a
visible browser and waits while a person signs in, ticking "Keep me logged in" — that is
what leaves `li_rm` in the profile, expiring a year out. Then pass the same
`user_data_dir` to `LinkedinScraper`, or `interactive_login=True` to have the sign in happen
from `run()` on the first run that finds no session. Chrome locks a profile directory, so
`max_workers` is forced to 1. "Keep me logged in" is unavailable on accounts with two factor
authentication enabled, which rules this path out there.

**The `SESSION_REFRESHED` event** covers callers with no persistent volume: the scraper
emits the cookie it ends up holding whenever it differs from the one supplied.

## The remember me credential can be carried to a host with no display

This closes the question the persistent profile left open. A profile seeded by injecting
`li_at` could not self-heal, because LinkedIn issues `li_rm` only to a real sign in — so a
remote host got persistence and no recovery. It turns out the credential travels.

Measured on pristine profiles that had never signed in, injecting cookies read out of a
profile that had:

| Injected | Result |
| --- | --- |
| `li_rm` | refused, `302 → /login` |
| `li_rm` + `bscookie` | refused, `302 → /login` |
| `li_rm` + `bcookie` | **session issued** |
| `li_rm` + `bcookie` + `bscookie` + `liap` + `JSESSIONID` + `lidc` + `li_mc` | session issued |

So the credential is `li_rm` bound to the `bcookie` it was issued to, and nothing smaller.
`bscookie` is not part of it, and cannot stand in for `bcookie`. Reading the pair out of a
profile did **not** rotate it: the source profile still worked afterwards.

`li_at` was never injected in any of those runs. The pair is a complete credential on its own,
which is what makes `LI_RM_COOKIE` + `LI_BCOOKIE` the way to authenticate where no browser can
be opened — and better than `LI_AT_COOKIE` even where one can, since it is asked for a fresh
session per run instead of being handed one that is already being retired.

Verified end to end, headless: the pair alone, no profile and no `LI_AT_COOKIE`, scraped 5 of 5
jobs with 0 errors. With a fresh `user_data_dir` as well, the profile was seeded with the pair,
then `li_at` was deleted from it, and a second run **with a completely empty environment**
recovered and scraped 3 of 3.

That second run only works because an injected pair is given an expiry. `add_cookie` without
one creates a session cookie, which Chrome discards when the browser closes: the first attempt
left the profile holding `li_at` and no `li_rm`, persisting the session but not the thing that
renews it. `bcookie` hid the bug by surviving anyway, since LinkedIn re-sends it with an expiry
of its own.

### Two traps in this area, both hit

- **Do not read the cookie jar straight after a navigation.** The driver uses a `'none'`
  page load strategy, so `driver.get` returns before the response carrying the cookie has
  been processed. Checking immediately reported no session on a profile that had one a
  second later, and the run bailed out with "the browser profile holds no session".
  `__wait_for_session` polls for up to `SESSION_WAIT_TIMEOUT`.
- **`Selectors.appShell` does not match the feed.** `.scaffold-layout, .global-nav` matches
  the jobs pages but not `/feed/`, whose class names are now obfuscated hashes. The login
  helper originally waited for it and hung forever on a perfectly good session; it now waits
  to be *past the sign in pages* instead. `__is_guest_page` still uses `appShell`, which is
  fine because it only ever runs on a jobs page.

### A third trap: the jar wins, so a stale profile can lock out a fresh credential

A session already in the jar takes precedence over anything supplied, which is what makes a
seeded profile usable with an empty environment. The same rule used to strand the caller: a
profile holding a retired `li_at` while a *fresh* `LI_AT_COOKIE` was supplied would prefer the
retired one, and the run died without the fresh cookie ever being tried. The only way out was
deleting the profile directory by hand.

`__open_results` now answers either refusal signature by deleting the session from the jar and
authenticating again from whatever credentials exist, then retrying the page once. Both
signatures take that path, since a cookie sitting in the jar says nothing about whether
LinkedIn honours it.

The cleared-cookie signature is covered by a test: seed a profile with a structurally invalid
`li_at`, supply a good `LI_AT_COOKIE`, and the run recovers and scrapes. The other signature —
cookie kept, logged out page served — is handled by the same code but has **not** been
reproduced, because LinkedIn clears an invalid cookie rather than keeping it, and a genuinely
retired-but-well-formed cookie cannot be produced on demand.

## Still open

Pagination is **intermittent**. It failed on two runs and succeeded on a third with an
identical configuration, which is why `__paginate` now waits as long as the initial
container wait, retries once, and describes the page when it gives up. The cause is not
established; rate limiting is the obvious suspect, and the `__describe_page` dump on the
next failure is the way in.

## Running the field validator

`PYTHONPATH` is required, in the container as well as locally: running the file by path puts
its own directory on `sys.path` rather than the one holding the package.

```shell
docker build --platform linux/amd64 -f tests/Dockerfile -t test_image .
docker run --rm --platform linux/amd64 \
  -e LI_AT_COOKIE="$LI_AT_COOKIE" -e PYTHONPATH=/app -e LOG_LEVEL=INFO -e LIMIT=30 \
  test_image python -u tests/manual/validate_fields.py
```

`--platform linux/amd64` is required on Apple Silicon: Chrome for Testing publishes no
linux-arm64 build, so the image runs under emulation and a 30-job run takes several minutes.

## Do not

- **Do not push to `master`.** `.github/workflows/ci.yml` publishes to PyPI on every push
  there.
- Do not add a `skills` field back to `EventData`: LinkedIn no longer exposes skill names,
  only a Premium-gated "N of M skills match" control.
- Do not index into `document.querySelectorAll('div.job-card-container')` by position. See
  the CLAUDE.md section on the virtualized list.
