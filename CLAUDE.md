# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`linkedin-jobs-scraper`: a PyPI package that scrapes public LinkedIn job postings by driving a headless Chrome instance through Selenium. There is a sibling npm package (`linkedin-jobs-scraper`) with equivalent behaviour — feature parity between the two is intentional.

## Commands

The `package.json` scripts are the canonical entry points (they wrap a conda env named `linkedin-jobs-scraper-selenium4`, Python 3.13 + `requirements.txt`):

```shell
npm run hooks    # git config core.hooksPath .githooks (once per clone)
npm run test     # pytest --capture=no --log-cli-level=DEBUG
npm run clean    # remove build/, dist/, *.egg-info, __pycache__, .pytest_cache
npm run build    # clean + python setup.py install_egg_info sdist bdist_wheel
npm run deploy   # twine upload to testpypi
```

`.githooks/pre-commit` bumps the patch version in `setup.py` and stages it, so every commit carries its own version. Git never enables a cloned repository's hooks on its own, so `npm run hooks` (or the `git config` behind it) is needed once per clone; `git commit --no-verify` skips it for a single commit. It stands down while git is replaying commits that already carry a version — merge, rebase, cherry-pick, revert — and when `setup.py` holds unstaged changes, which staging the bump would sweep into the commit.

The cost is structural, not a defect: every commit touches the same line, so branches that diverge collide on it, and a cherry-pick across them stops on a conflict in `setup.py`. Versions also count commits rather than releases. Bumping on push to `master`, or deriving the version from a git tag, are the two ways out if that becomes tiresome.

Running tests directly, which is also exactly what CI does:

```shell
LI_RM_COOKIE=<li_rm> LI_BCOOKIE=<bcookie> pytest --capture=no --log-cli-level=DEBUG
LI_RM_COOKIE=<li_rm> LI_BCOOKIE=<bcookie> pytest tests/test_.py::test_run   # the only test
```

Selenium Manager fetches a chromedriver matching the local Chrome, so there is nothing to install — but it will not override a mismatched chromedriver already on `PATH`, so locally `PATH="/usr/bin:/bin"` is the way to keep it out of the way.

**Tests hit the live LinkedIn site.** There are no unit tests and no fixtures: `tests/test_.py` runs real queries and `tests/shared.py` asserts on the shape of each emitted `EventData`. A failing test usually means LinkedIn changed its DOM (see *Selectors*), not that the Python logic broke. A credential is required — use the remember me pair rather than `LI_AT_COOKIE`, which the suite exhausts in about two runs.

`tests/manual/` holds standalone probes that need no live LinkedIn: `throttle_backoff.py` (backoff ladder and pacer, against a local server), `mid_run_recovery.py`, `remote_probe.py`, `network_headers_probe.py`, `validate_fields.py`.

Release: pushing to `master` publishes to PyPI via `.github/workflows/ci.yml`. Version is declared only in `setup.py` (`package.json`'s version is unused). Because a push to `master` publishes, never push there without the maintainer explicitly asking.

## Architecture

Flow: `LinkedinScraper.run(queries)` → one `ThreadPoolExecutor` task per `Query` → **one Chrome driver per task**, reused across the loop over `query.options.locations`, delegating to `AuthenticatedStrategy`. One browser per query rather than per location, because every new browser is another session establishment for LinkedIn to look at.

### The driver must not look automated

Two signals used to end the session after a single run, and both are now suppressed: the `HeadlessChrome` token Chrome puts in the `User-Agent` under `--headless=new`, and `navigator.webdriver`, which `--enable-automation` sets. `get_default_driver_options` drops the switch via `excludeSwitches`, and the `User-Agent` is fixed in two places:

- **At launch, via `--user-agent`**, which is the one that matters, because **every target inherits it** — including the separate tab `__extract_apply_link` opens, which lands on LinkedIn carrying the session cookie. `resolve_masked_user_agent` spends one short lived browser per process to read the browser's own `User-Agent` and caches the de-headlessed result.
- **Over CDP, via `mask_headless_user_agent`**, covering the main target when a caller supplies their own `chrome_options` and the flag cannot be injected. Idempotent: once the token is gone it returns `None`.

Constraints on the masking:

- The replacement `User-Agent` is **derived from the running browser**, never hardcoded. A stale hardcoded string is worse than the leak it hides.
- `userAgentMetadata` must be passed, read from `navigator.userAgentData`, or the `Sec-CH-UA` headers stop agreeing with the `User-Agent`.
- `acceptLanguage` must **not** be passed: Chrome appends a second quality value to every entry, producing a malformed header. `--lang` already yields a correct `Accept-Language`.
- It runs in `AuthenticatedStrategy.run` immediately after the first navigation and before the cookie is injected: `navigator.userAgentData` is unavailable on the `data:,` page a driver starts on, and that first request is unauthenticated so it can afford to carry the token.

Do not add `--disable-web-security` back. It is inert without `--user-data-dir`, and the persistent profile would switch it on — a disabled same-origin policy is detectable from the page.

### One strategy, built once at construction

`LinkedinScraper.__init__` builds `AuthenticatedStrategy` unconditionally and every query thread calls `run()` on that one instance. The constructor cannot see whether a session exists — a `user_data_dir` profile carries its own, and a caller can put `--user-data-dir` in their own `chrome_options` — so it only **warns** when nothing it can see names a credential, and `__authenticate` holds the verdict until a browser is open.

A run with no credential logs one error per location, emits `END` and produces nothing; nothing raises. `run` returns before `__open_results`, which is the only place that emits `INVALID_SESSION` or raises `InvalidCookieException`.

Every `Config` value is read from the environment **at import time** (`config.py`), so setting `os.environ` after importing the package has no effect.

`strategies/strategy.py` stays as the `run(driver, search_url, query, location, page_offset)` contract and the type `self._strategy` is annotated with. `AnonymousStrategy` was removed in 6.0.0; do not add a second strategy back for the no-credential case, because there is nothing to scrape without a credential.

### Two credentials, and they are not equivalent

`AuthenticatedStrategy.__authenticate` prefers the first:

- **The remember me pair**, `LI_RM_COOKIE` + `LI_BCOOKIE` (`li_rm` and `bcookie`). LinkedIn mints a fresh `li_at` for it on any authenticated route. It lasts a year and renews itself, so it is the path both documented modes end up on.
- **`LI_AT_COOKIE`**, a session cookie handed over as is. Nothing can renew it and LinkedIn retires it after roughly a hundred job loads.

Rules for the pair:

- It is the pair and nothing smaller: `li_rm` alone is refused, and so is `li_rm` next to a different browser's browser id.
- **A pair copied out of an everyday browser is refused** — the mechanism is unknown, but it is the credential and not the machine, the browser or the account. `python -m linkedin_jobs_scraper.login` is the only supported source, and the README must not tell anyone to use devtools for it. `li_at` on its own is unaffected and still copyable.
- An injected pair **must carry an expiry** (`REMEMBER_COOKIE_MAX_AGE`). `add_cookie` without one creates a session cookie Chrome discards on exit, leaving a profile holding a session and nothing able to renew it.
- `bcookie` is not `HttpOnly` and lives on `.linkedin.com`, not `.www.linkedin.com` like the other two.

### Sessions: the profile wins

`utils/session.py` owns the cookies a session is made of. `user_data_dir` gives the browser a profile that survives across runs, and a session already in that jar takes precedence over anything supplied, which is what lets a profile be seeded once and then run with an empty environment. Chrome locks a profile directory, so `max_workers` is forced to 1 when one is set.

Recovery from a retired session needs **no UI automation**: with `li_rm` present, a request to an authenticated route has a fresh session issued silently, so `__recover_session` navigates to `FEED_URL` and waits.

`interactive_login` is the only path that opens a visible browser, requires `user_data_dir`, and is off by default because it waits up to 10 minutes for a human. `login.ensure_session` spends one short lived headless browser deciding whether a sign in is needed at all (`has_credentials`), and runs in `run()` before any worker starts, because Chrome locks the profile.

Three traps:

- **Never read the cookie jar straight after a navigation.** `page_load_strategy` is `'none'`, so `driver.get` returns before the response carrying the cookie is processed. `__wait_for_session` polls for up to `SESSION_WAIT_TIMEOUT`.
- **Never read the cookie jar without asking where the browser is.** `driver.get_cookie` returns the jar of the *document on screen*, so on an error page — a network failure, an HTTP 429 — it reads empty whatever session the browser holds, and cookies cannot be injected there either (`InvalidCookieDomainException`). `__is_session_lost` is the check to use: `__is_on_linkedin` **and** no session cookie. `__wait_for_linkedin` guards every point where a credential is about to be injected. Nothing may conclude "the session is gone" from the cookie alone.
- **A supplied pair must not overwrite a profile's own.** `li_rm` is bound to the `bcookie` it was issued with, so replacing half of a profile's pair with half of somebody else's breaks both. `__authenticate` injects only when the jar holds no `li_rm`.

`__open_results` answers a refusal by emptying the jar of its session, authenticating once more and retrying the page — which is what makes a fresh credential usable against a profile holding a retired one. Both of LinkedIn's refusals are treated the same, since the jar proves nothing either way. If the retry gets a session that still renders no results the location is skipped (throttling looks exactly like that); if it gets no session at all, it emits `INVALID_SESSION` and `InvalidCookieException` aborts the run.

**Recovery also happens mid-run.** The pagination loop, the jobs loop and the pagination-failure path all route back through `__open_results` on the page they are on. Three things hold it together: `MAX_SESSION_RECOVERIES` caps it per location, so "reissued, then refused again" cannot loop; `processed_ids` is scoped to the location, so re-opening a page half way through it does not emit its jobs twice; and pagination questions the session only after failing twice, because a page that will not render is usually just a page that will not render. `INVALID_SESSION` therefore means *every credential was refused*, and fires only where `__open_results` gives up.

`tests/manual/mid_run_recovery.py` reproduces all of it, monkey-patching the deletion in rather than putting a hook in shipped code. It deletes `li_rm` alongside `li_at`, since LinkedIn silently mints a replacement while `li_rm` is still in the jar.

### Filters are LinkedIn URL query params

Enum values in `filters/filters.py` *are* LinkedIn's own URL codes; `LinkedinScraper.__build_search_url` maps them onto param names:

| Filter | Param |
| --- | --- |
| `company_jobs_url` (extracts `f_C`) | `f_C` |
| `relevance` | `sortBy` |
| `time` | `f_TPR` |
| `base_salary` | `f_SB2` |
| `type` | `f_JT` |
| `experience` | `f_E` |
| `industry` | `f_I` |
| `on_site_or_remote` | `f_WT` |

Adding a filter means: add the enum member with the code copied from a real LinkedIn search URL, add the mapping in `__build_search_url`, add validation in `QueryFilters.validate`, and document it in the README's filter list.

### Option merging and defaults

`Query.merge_options` fills per-query `None` fields from the global `QueryOptions` passed to `run()`, falling back to hardcoded defaults (`limit=25`, `apply_link=False`, `skip_promoted_jobs=False`, `page_offset=0`). If no global options are given, `run()` synthesises `QueryOptions(locations=['Worldwide'], limit=25)`. Pagination is driven by the `start` query param in steps of `PAGINATION_SIZE` (25, LinkedIn's page size); `page_offset` is a page count, not a job count.

### The results list is virtualized — iterate by job id, never by position

This is the single most important invariant. LinkedIn renders only a handful of job cards at a time and removes the rest from the DOM ("occludable" list), so `document.querySelectorAll('div.job-card-container')` returns a *moving subset* of the page, typically 7–12 of 25. Indexing into that NodeList silently reads the wrong job.

Every item of the list, rendered or not, carries `data-occludable-job-id` (`JOB_ID_ATTRIBUTE`). `AuthenticatedStrategy.__get_job_ids` enumerates those ids once per page, and the jobs loop addresses each job through `get_job_item_selector(job_id)`. `__load_job_card` scrolls an item into view and polls until its card exists before any field is read. Do not reintroduce positional access.

**The first render of a page is not the page.** LinkedIn paints a preliminary list and replaces it about a second later, and the two do not always hold the same jobs — the preliminary one is partly made of items belonging to a different page, so ids read from it address items that are about to stop existing. Nothing in the DOM marks it; only its size does, since every preliminary render measured held 7 items where the settled one held `PAGINATION_SIZE`. `__wait_for_stable_job_ids` therefore requires a full batch *and* `LIST_SETTLE_QUIET_PERIOD` of no change, falling back to `LIST_SETTLE_TIMEOUT` for the last page of results, which genuinely holds fewer. It seeds the jobs loop and runs at the top of the pagination loop, costing ~1–2 s per page.

Treat that wait as an optimisation, not a guarantee — the guarantee is the layer below it. LinkedIn can re-render at any point, so `__load_job_card` answers `missing` when the item is not in the list at all (after `MISSING_ITEM_GRACE`, so a momentary detachment does not count) and the jobs loop skips those ids without touching `metrics.failed`. Only an item that *is* present but never renders a card is a failure. Do not collapse the two answers back into one bool.

The list's own scroll container has a runtime-generated obfuscated class name, so it cannot be selected by class; reach it structurally (walk up from the `ul` to the first scrollable ancestor).

### Extraction is JavaScript, not Selenium

Nearly all field extraction is a `driver.execute_script(...)` call with CSS selectors passed as `arguments[n]`. Selenium's own element API is barely used. Waiting is done with hand-rolled poll loops (`__load_job_card`, `__load_job_details`, `__paginate`) that sleep 50 ms and time out, not `WebDriverWait` (one exception: the initial container wait).

Chrome DevTools Protocol is used directly for what Selenium cannot do: `Network.setUserAgentOverride` for the headless masking, and `Target.getTargets` / `Target.closeTarget` to capture the off-site apply URL from the tab LinkedIn opens (`__extract_apply_link`).

`__paginate` waits as long as the initial container wait and reports `__describe_page` when it gives up — pagination is intermittent, so that dump (status, ready state, container and guest markers, item count, title, URL, leading visible text) is the way into the next failure. It retries once after `PAGINATION_RETRY_DELAY`, but not when the page came back throttled, since the backoff has already waited that out.

### A 429 is readable, and it is the one failure worth waiting through

LinkedIn answers a run that is going too fast with an HTTP 429 carrying **no body**, so Chrome discards the response and shows its own error page. The browser is then on `chrome-error://chromewebdata/`, where there is no container to wait for and no cookie jar to read. The status survives on `performance.getEntriesByType('navigation')[0].responseStatus`, which reports 429 on Chrome's own error page and needs no CDP Network domain; `__get_response_status` / `__is_throttled` read it and `__describe_page` prints it as `status=`.

`__open_and_wait` owns the response: it opens a url, runs the caller's wait, and — **only** when the reply was a 429 — sleeps and asks again, through `THROTTLE_BACKOFF_DELAYS` (5 s, 15 s, 45 s). Every other outcome goes straight back to the caller, so a genuinely unrendered page still fails fast. `jittered_backoff` spreads each step by `THROTTLE_BACKOFF_JITTER` (±50%) so two workers refused in the same moment do not ask again in the same moment. It is deliberately not full jitter (`uniform(0, base)`): a 429 is cleared by time, so a first wait near zero spends the attempt for nothing. Both `__open_results` and `__paginate` go through it.

A successful open is deliberately **not** reported to the pacer as clean work — `__slow_down` is called from both `__observe_resources` and `__open_and_wait`, `__speed_up` only from the former. The unit easing is earned in is a job, and jobs vastly outnumber navigations.

Throttling and a retired session look alike: `__is_session_lost` remains the check, and a 429 must never be answered by spending a credential.

**The backoff ladder is invented and stays invented.** `Retry-After` (RFC 6585 §4) would be the obvious replacement, and it was measured rather than argued: LinkedIn sends no `Retry-After` on a 429 and no `X-RateLimit-*` on anything, over 312 refusals captured passively over WebDriver BiDi. Do not reopen the BiDi question without new evidence — LinkedIn starting to send the header, or Selenium promoting the passive event API to its supported surface and fixing `network.continueResponse`, which currently wedges the browser. `tests/manual/network_headers_probe.py` is the instrument to re-run.

**A navigation is not the only thing that gets throttled, and it is not even the common case.** Job details are fetched by LinkedIn's own JavaScript rather than navigated to, so a 429 there never reaches `__is_throttled` — it surfaces as `Timeout on loading job details` and inflates `metrics.failed` with no hint of the cause. `PerformanceResourceTiming.responseStatus` carries it, and the same-origin `voyager/api/…` calls that matter all report a real status. (Cross-origin assets with no `Timing-Allow-Origin` report `0`, which is harmless: `0` is never 429.)

`__count_throttled_resources` counts the 429s in that buffer and `__observe_resources` turns the count into a signal by comparing it against the previous reading: a delta means a refusal, an unchanged count means clean work. It runs once per job, in the `finally` of the per-job try, because the failure paths are exactly the ones a throttle leaves through.

**A count is only comparable within one document.** The buffer belongs to the document and goes away with it, and a fresh document reports `0` — indistinguishable from a document nobody refused anything, which is how a count-only comparison came to vote *clean* on every document swap and ease a pace no work had earned. So every reading is a `(time_origin, count)` pair, `performance.timeOrigin` being set when the document is created: a different origin re-baselines silently whatever the counts say. Three details hold:

- The initial baseline is `None`, not `0` — there is no document yet, and no number could stand for that.
- A count that goes *down* under an unchanged origin re-baselines silently too: the page cleared its own timings.
- `__count_throttled_resources` returns `None` rather than `0` when the buffer cannot be read, because `0` would look like a reset and then report the whole buffer as fresh refusals.

The buffer holds 250 entries by default, which one page of results fills on its own, so `__open_and_wait` raises it to `RESOURCE_TIMING_BUFFER_SIZE` on every successful open — raising, never `clearResourceTimings()`, which would destroy timing data the page itself may be reading.

**The baseline is a local in `run()` and must stay one.** One strategy instance serves every query thread, so anything on `self` is shared by all of them.

### The pace is discovered, not configured

`utils/pacing.py` owns every number involved. `slow_mo` is the **floor** the run never goes below, not the pace it keeps: `Pacer` doubles the delay on each refusal up to `min(PACING_CEILING_LIMIT, slow_mo * PACING_CEILING_FACTOR)` and eases it by `PACING_EASE_FACTOR` after `CLEAN_RUN_BEFORE_EASING` jobs nobody refused. Easing is deliberately slower than raising, because the limit looks cumulative.

**One pacer per `LinkedinScraper`, shared across its query threads under a lock.** The limit is enforced per account, so a 429 one worker meets is a reason for all of them to slow down. This is the opposite of the resource-timing baseline above, and for the opposite reason: that counter belongs to a document, this one to an account.

`slow_mo` below `MIN_SLOW_MO` (0.2) raises at construction, because `0` produced a ceiling of `min(10, 0) = 0` and switched the whole mechanism off silently. With that minimum the ceiling is never below 2 s, so there is no configuration where `adaptive_slow_mo=True` does nothing. `adaptive_slow_mo=False` builds a pacer whose ceiling equals its floor, which makes `min(delay * factor, ceiling)` inert without a special case anywhere: the sleep sites read `scraper.pacer.delay` either way, and `scraper.slow_mo` stays the number the caller asked for.

`EventMetrics` carries `throttled` (429s seen) and `pace` (what is being slept now). The count is kept even on an inert pacer, so the two modes stay comparable.

`slow_mo` defaults to `0.8` and `max_workers` to a single worker in the README's recommendation. Increasing default concurrency, or lowering that default, is a behavioural regression, not an optimisation.

### Selectors are the fragile surface

The strategy declares a `Selectors` class at the top of its module. This is where breakage concentrates when LinkedIn ships a UI change, and the git history is mostly selector fixes.

- "Promoted" detection matches the literal string `'Promoted'` in a list item, so it is locale-dependent — the driver forces `--lang=en-GB` for this reason.
- `date_text` reads `…top-card__tertiary-description-container`, whose text is `<place> · <date> · <applicants>` with any segment possibly absent. The date is matched by shape (`/\bago\b|just now/i`) rather than by position, because positional selectors on this node break whenever a segment is missing.
- Job "insights" (on-site/remote, contract type, skill-match summary) are `<button>` elements inside `.job-details-fit-level-preferences`, not list items.
- LinkedIn no longer exposes required-skill names anywhere in the DOM, only a Premium-gated "N of M skills match" control, so `EventData` has no `skills` field. Do not add one back without checking the live DOM first.
- `Selectors.appShell` does not match `/feed/`, whose class names are obfuscated hashes; it matches the jobs pages only. `login.py` waits to be past the sign in pages (`Selectors.signInForm` plus `SIGN_IN_PATHS`) instead.

The strategy also defensively dismisses UI that blocks scraping on every pagination round: `__accept_cookies`, `__dismiss_global_alert`, `__close_chat_panel`. `__dismiss_global_alert` clicks `button.artdeco-global-alert__dismiss` by selector, deliberately not by button text, so it works regardless of locale.

### Events

`LinkedinScraper` is a small event emitter (`on` / `once` / `emit` / `remove_listener`). Callback arity is validated at registration: `DATA`, `ERROR`, `METRICS`, `SESSION_REFRESHED` take exactly one argument; `END` and `INVALID_SESSION` take zero. Only `FunctionType` values pass the `isinstance` check, so plain functions and lambdas work but bound methods and callable objects are rejected.

`SESSION_REFRESHED` carries an `EventSession` and fires when the cookie the browser ends up holding differs from `Config.LI_AT_COOKIE`, so a caller with no persistent profile can store it for the next run.

An exception raised inside a user callback is wrapped as `CallbackException` and re-raised out of `run()`, aborting the scrape. `InvalidCookieException` propagates the same way. Every other exception is swallowed and re-emitted as an `ERROR` event so the run continues. `END` is emitted per query thread, not once per `run()`.

`EventData` is a `NamedTuple`; adding or removing a field means also updating the README's field list and `tests/shared.py`. Note that `x in data` on a `NamedTuple` tests *values*, not field names — never use it to probe for a field's presence.

## Gotchas

- Logging goes through `utils/logger.py` to the `li:scraper` namespace; level comes from the `LOG_LEVEL` env var (read at import time). `logger.py` truncates each argument at 1000 chars.
- `tests/manual/validate_fields.py` needs `PYTHONPATH` set to the directory holding the package. Running a file by path puts *its own* directory on `sys.path`, not the working directory, so without it the import of `linkedin_jobs_scraper` fails.
- There is no proxy support. A dead, broken proxy API was removed in 6.0.0; adding real support means wiring `--proxy-server` into `get_default_driver_options`, not restoring the old shape.
- `docs/` and `tmp/` are gitignored scratch space, not part of the package.
- Chrome/chromedriver version compatibility is the most common source of local-only failures, and Selenium Manager will *not* rescue a mismatched driver already on `PATH` — it warns and then fails with `SessionNotCreatedException`. `chrome_executable_path` (chromedriver) and `chrome_binary_location` (Chrome/Chromium binary) let a caller pin a matched pair; running with `PATH="/usr/bin:/bin"` hides the stray driver and lets Selenium Manager fetch a matching one.
