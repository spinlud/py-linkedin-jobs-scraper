# Handoff: `li_at` session revocation during headless runs

Status as of 2026-08-05. Written to be picked up in a fresh session with no prior context.

## The problem in one line

LinkedIn revokes the `li_at` session cookie after roughly **one** headless scraping run, so
every attempt to finish the end-to-end verification costs a freshly harvested cookie.

## What was observed

Four different cookies were supplied during one working session. Each one:

1. was valid when first checked,
2. survived exactly one scraper run (5–8 jobs),
3. was **actively deleted** by LinkedIn afterwards.

The revocation is server side and unambiguous. A plain HTTP request — no browser, no
Selenium — comes back with:

```
set-cookie: li_at=delete me; Version=1; Path=/; Domain=.www.linkedin.com;
            Expires=Thu, 01-Jan-1970 00:00:00 GMT; Max-Age=0; Secure; SameSite=None; HttpOnly
```

Incidentally this also confirms that the odd-looking cookie domain the scraper uses,
`.www.linkedin.com` (`authenticated_strategy.py`), is what LinkedIn itself sets. It is not a bug.

### Check a cookie without spending a run

Always do this before starting a container run — it takes two seconds and saves ten minutes:

```shell
curl -s -o /dev/null -D /tmp/h.txt \
  -H "Cookie: li_at=$LI_AT_COOKIE" \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36" \
  "https://www.linkedin.com/jobs/search/?keywords=test"
grep -iE "^set-cookie: li_at=delete" /tmp/h.txt && echo REVOKED || echo ALIVE
```

## Why this matters beyond testing

This is very likely a **product** problem, not a test-harness problem. Anyone using the
library hits the same wall: their session dies after a run and they have to re-harvest the
cookie by hand. Treat it as a bug in the package, not an inconvenience for the maintainer.

## Leading hypothesis: the driver advertises itself as automated

`utils/chrome_driver.py:get_default_driver_options` and `linkedin_scraper.py:__run` set, among
other things:

| Setting | Effect |
| --- | --- |
| `--enable-automation` | sets `navigator.webdriver = true`, the single most-checked automation signal |
| `--disable-web-security` | disables same-origin policy, an unusual real-user configuration |
| `Page.setBypassCSP` (CDP) | disables Content Security Policy enforcement |
| `Network.enable` (CDP) | attaches a CDP network domain for the whole session |

Any of these is trivially detectable from page JavaScript. Note the repo has already been
here once: commit `6520ae2 Disabled random user agent` turned off the random UA override with
the comment *"This can cause the session cookie to be invalidated earlier then expected"* —
the same failure mode, a different trigger.

**This has not been tested.** It is a hypothesis with good circumstantial support, not a
diagnosis. Removing these flags is a behaviour change, so it was deliberately left for the
maintainer to decide rather than folded into 6.0.0 silently.

### Suggested experiment

Change one variable at a time, checking cookie state before and after each run:

1. Baseline: current flags, `limit=8`, `apply_link=False`. Confirm the cookie dies.
2. Drop `--enable-automation` only. Re-run. Cookie still alive?
3. Drop `--disable-web-security`. Re-run.
4. Drop `Page.setBypassCSP` — but note `__extract_apply_link` may depend on CDP behaviour,
   so verify apply-link capture still works before concluding.

`Network.enable` and `Page.setBypassCSP` are set in `linkedin_scraper.py:__run`; the Chrome
flags are in `utils/chrome_driver.py:get_default_driver_options`.

A second, non-exclusive hypothesis worth ruling out: request rate. Runs were issued in quick
succession from the same IP. `slow_mo` throttles between jobs but nothing throttles between
runs.

## How to tell revocation apart from a DOM break

These two failures used to look identical, which sent debugging in the wrong direction. The
code now distinguishes them, so read the log message rather than guessing:

- `InvalidCookieException` — the cookie was dropped from the jar entirely. Session is dead.
- `LinkedIn served the logged out page: the session cookie was rejected or the requests are
  being throttled` — emitted by `__is_guest_page`. The cookie is *in the jar* but LinkedIn
  ignored it and served the guest page. **A cookie sitting in the jar does not mean the
  session is honoured**, which is why `__is_authenticated_session` alone is not a sufficient check.
- `Results container .scaffold-layout__list never appeared` — genuinely authenticated but the
  DOM changed. This is the one that means "go fix selectors".

## Verification state of the 6.0.0 work

Everything below was verified against live LinkedIn except the last row.

| Area | State |
| --- | --- |
| All `EventData` fields, strict shape checks | **0 violations** across two independent runs (6 and 5 records) |
| `title` / `company` / `place` correctness | Cross-checked against public `/jobs/view/<id>/` pages for 3 jobs — exact match |
| `job_id` ↔ `link` association | Verified: every `job_id` appears in its own `link` |
| `apply_link` (CDP off-site tab capture) | Working: real hosts `www.amazon.jobs`, `careers.tripadvisor.com`, `morganstanley.eightfold.ai`, `jobs.ashbyhq.com` |
| `description_html` | Content verified, not just length: starts with a tag and contains the plain text |
| `insights` (new selector) | Populated on every record, including salary and skill-match entries |
| `date_text` (shape-matched, not positional) | Valid relative dates, no `·` separator leakage |
| Docker base image | Built and run: Chrome for Testing 151.0.7922.71 + ChromeDriver 151.0.7922.71 |
| **List growth past ~12 cards, and pagination** | **NOT VERIFIED** — every run died before reaching the boundary |

### The one open verification

The results list is virtualized: only ~7–12 cards exist in the DOM at a time, and the
`li[data-occludable-job-id]` placeholders are themselves appended progressively. Both
`__load_more_jobs` (growing the id list) and the `?start=25` pagination hop are therefore
**unproven** — every run so far stopped at 5–8 records, inside the initially rendered window.

To close it, run with `apply_link=False`, which avoids the tab churn that caused the earlier
crashes:

```shell
docker build --platform linux/amd64 -f tests/Dockerfile -t test_image .
docker run --rm --platform linux/amd64 \
  -e LI_AT_COOKIE="$LI_AT_COOKIE" -e LOG_LEVEL=INFO -e LIMIT=30 -e APPLY_LINK=false \
  test_image python -u tests/manual/validate_fields.py
```

Success criteria: `records collected: 30 of 30`, `TOTAL VIOLATIONS: 0`, 30 unique job ids, and
at least one `Pagination requested` line in the log.

`--platform linux/amd64` is required on Apple Silicon: Chrome for Testing publishes no
linux-arm64 build. It runs under emulation, so a 30-job run takes several minutes.

## Bugs found while chasing this

Both only surface with `apply_link=True`, which is why an early smoke run missed them.

1. **`Target.closeTarget` on non-closable targets** — *pre-existing since at least 5.0.2*. The
   leftover-tab cleanup called `Target.closeTarget` on every CDP target, including service
   workers and the browser target, which raises `invalid argument: Specified target doesn't
   support closing`. Worse, the block was `try: ... finally:` with **no `except`**, so the
   exception propagated and aborted the whole query. Fixed by filtering `type == 'page'` and
   adding an `except` that degrades to a warning.

2. **`__get_job_ids` returning `None`** — introduced by the 6.0.0 occludable rewrite.
   `execute_script` returns `null` while the document is being replaced, which happens during
   apply-link tab churn, giving `TypeError: 'NoneType' object is not iterable`. The call sat
   outside the per-job `try`, so it killed the query. Now returns `[]` and never raises;
   `__load_more_jobs` was hardened the same way against `None > int`.

## Still unexplained

In one run an `apply_link` pointed at `www.linkedin.com` rather than an external site.
`__extract_apply_link` captures "any attached page target whose url differs from the current
one", so an interstitial or a second LinkedIn tab could be mis-captured. `validate_fields.py`
now prints every `apply_link` value and flags LinkedIn hosts, so the next run with
`APPLY_LINK=true` will show whether this is real.

## Do not

- **Do not push to `master`.** `.github/workflows/ci.yml` publishes to PyPI on every push
  there. The 6.0.0 work is on the branch `chore/v6.0.0-linkedin-dom-update`.
- Do not add a `skills` field back to `EventData` without checking the live DOM: LinkedIn no
  longer exposes skill names anywhere, only a Premium-gated "N of M skills match" control.
- Do not index into `document.querySelectorAll('div.job-card-container')` by position. That is
  the bug 6.0.0 exists to fix; see the CLAUDE.md section on the virtualized list.
