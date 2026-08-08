# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`linkedin-jobs-scraper`: a PyPI package that scrapes public LinkedIn job postings by driving a headless Chrome instance through Selenium. There is a sibling npm package (`linkedin-jobs-scraper`) with equivalent behaviour — feature parity between the two is intentional.

## Commands

The `package.json` scripts are the canonical entry points (they wrap a conda env named `linkedin-jobs-scraper-selenium4`, Python 3.13 + `requirements.txt`):

```shell
npm run test     # pytest --capture=no --log-cli-level=DEBUG
npm run clean    # remove build/, dist/, *.egg-info, __pycache__, .pytest_cache
npm run build    # clean + python setup.py install_egg_info sdist bdist_wheel
npm run deploy   # twine upload to testpypi
```

Running tests directly, which is also exactly what CI does:

```shell
LI_RM_COOKIE=<li_rm> LI_BCOOKIE=<bcookie> pytest --capture=no --log-cli-level=DEBUG
LI_RM_COOKIE=<li_rm> LI_BCOOKIE=<bcookie> pytest tests/test_.py::test_run   # the only test
```

There is no container and no browser to install: Selenium Manager fetches a chromedriver matching the Chrome already on the machine, and the GitHub runner ships one. The one thing it will not do is override a mismatched chromedriver already on `PATH`, so locally `PATH="/usr/bin:/bin"` is the way to keep it out of the way.

**Tests hit the live LinkedIn site.** There are no unit tests and no fixtures — `tests/test_.py` runs real queries and `tests/shared.py` asserts on the shape of each emitted `EventData`. A failing test usually means LinkedIn changed its DOM (see *Selectors* below), not that the Python logic broke. A credential is required; without one the scraper falls back to the unmaintained anonymous strategy and the test will produce nothing. Use the remember me pair, not `LI_AT_COOKIE`: the suite spends about 52 job loads and LinkedIn retires a session cookie after roughly a hundred, so a harvested cookie survives two runs.

Release: pushing to `master` publishes to PyPI via `.github/workflows/ci.yml`. Version is declared only in `setup.py` (`package.json`'s version is unused). Because a push to `master` publishes, never push there without the maintainer explicitly asking.

## Architecture

Flow: `LinkedinScraper.run(queries)` → one `ThreadPoolExecutor` task per `Query` → **one Chrome driver per task**, reused across the loop over `query.options.locations`, delegating to a `Strategy`. One browser per query rather than per location: every new browser is another session establishment for LinkedIn to look at.

### The driver must not look automated

This is what kept ending the session after a single run, and the details are in `docs/li-at-cookie-revocation.md`. Two signals mattered, both measured:

- Chrome in `--headless=new` puts a `HeadlessChrome` token in the `User-Agent` of every request, header and `navigator.userAgent` alike.
- `--enable-automation` sets `navigator.webdriver`.

`get_default_driver_options` drops the switch via `excludeSwitches`, and the `User-Agent` is fixed in two places:

- **At launch, via `--user-agent`**, which is the one that matters. `resolve_masked_user_agent` spends one short lived browser per process to ask the browser for its own `User-Agent` (`navigator.userAgent` is readable on the initial blank page; `navigator.userAgentData` is not) and caches the de-headlessed result. A launch flag is used rather than CDP because **every target inherits it**: the tab `__extract_apply_link` opens is a separate target that lands on LinkedIn carrying the session cookie before being redirected off site, and over CDP it would still have announced itself as headless. That leak ended a session during a 27-job `apply_link=True` run.
- **Over CDP, via `mask_headless_user_agent`**, as a fallback covering the main target when a caller supplies their own `chrome_options` and the flag cannot be injected. It is naturally idempotent: once the token is gone it returns `None`.

Three constraints on `mask_headless_user_agent`, each learned the hard way:

- The replacement `User-Agent` is **derived from the running browser**, never hardcoded. A stale hardcoded string is what made commit `6520ae2` worse than the leak it was hiding, and it is why `utils/user_agent.py` no longer exists.
- `userAgentMetadata` must be passed, read from `navigator.userAgentData`, or the `Sec-CH-UA` headers stop agreeing with the `User-Agent`.
- `acceptLanguage` must **not** be passed: Chrome appends a second quality value to every entry, producing a malformed header. `--lang` already yields a correct `Accept-Language`.

The masking runs in `AuthenticatedStrategy.run`, immediately after the first navigation and before the cookie is injected: `navigator.userAgentData` is unavailable on the `data:,` page a driver starts on, and that first request is unauthenticated so it can afford to carry the token.

`--disable-web-security` was removed. Chrome ignores it unless `--user-data-dir` is set, so it was inert — but adding the persistent profile would have switched it on, and a disabled same-origin policy is detectable from the page. `Network.enable` and `Page.setBypassCSP` were removed as unused CDP surface; `apply_link=True` was re-verified afterwards.

### Strategy selection happens once, at construction

`LinkedinScraper.__init__` picks `AuthenticatedStrategy` if any credential or `user_data_dir` is set, otherwise `AnonymousStrategy`. An **incomplete** remember me pair counts as a credential on purpose: the authenticated strategy says which half is missing, where the anonymous one would quietly find nothing. Every `Config` value is read from the environment **at import time** (`config.py`), so setting `os.environ` after importing the package has no effect.

`AnonymousStrategy` is explicitly unmaintained (it logs a warning and its selectors are stale). Treat `strategies/authenticated_strategy.py` as the only live scraping path unless asked otherwise.

### Two credentials, and they are not equivalent

`docs/session-credentials.md` is the findings document for this, and it marks every claim as verified, observed, inferred or unproven — read it before extending any of this, particularly the *What is not proven* section.

A session can start from either, and `AuthenticatedStrategy.__authenticate` prefers the first:

- **The remember me pair**, `LI_RM_COOKIE` + `LI_BCOOKIE` (`li_rm` and `bcookie`). This is *asked* for a session: LinkedIn mints a fresh `li_at` for it on any authenticated route. It lasts a year and it renews itself, so it is the path both documented modes end up on.
- **`LI_AT_COOKIE`**, a session cookie handed over as is. Nothing can renew it and LinkedIn retires it after roughly a hundred job loads. It only exists for accounts that never receive `li_rm` — two factor authentication being the usual reason — so do not present it as the normal way in.

Measured facts about the pair, all on a pristine profile that had never signed in:

- `li_rm` **alone is refused** (redirect to `/login`), and so is `li_rm` next to a different browser's `bscookie`. With `bcookie` it works. So the credential is the pair `li_rm` + `bcookie` and nothing smaller; `bscookie`, `liap`, `JSESSIONID`, `lidc` and `li_mc` are not needed.
- `bcookie` is **not** `HttpOnly` and lives on `.linkedin.com`, not `.www.linkedin.com` like the other two.
- **The pair travels between machines**: one issued by the login command on macOS was redeemed from a Google Cloud VM, container running Chrome 151 on Linux, different IP — LinkedIn minted a session. That is what makes the server mode a measurement rather than an intention; `tests/manual/remote_probe.py` reproduces it and is standalone so it can be copied to a host with no clone of this repo.
- **A pair copied out of an everyday browser is refused**, even though both halves are readable in the developer tools panel. `docs/remember-me-portability.md` is the investigation log for this, including the open points. The controlling experiment: that browser's `li_at` + `li_rm` + `bcookie` in one throwaway profile, LinkedIn serves the authenticated feed, then `li_at` is deleted and `li_rm` is asked for a replacement in that same browser seconds later — refused. So the redeeming browser, the machine and the account are all excluded, and it is the credential. Truncation, rotation, the quotes in `bcookie`'s value, DBSC and every device-ish cookie were ruled out too; the mechanism is unknown. The login command is the only supported source of the pair, and the README must not tell anyone to use devtools for it. `li_at` on its own is unaffected and still copyable.
- An injected pair **must carry an expiry** (`REMEMBER_COOKIE_MAX_AGE`): `add_cookie` without one creates a session cookie that Chrome discards on exit, which left a profile holding a session and nothing able to renew it. `bcookie` masked the bug by surviving anyway — LinkedIn re-sends it with an expiry of its own.

### Sessions: the profile wins

`utils/session.py` owns the cookies a session is made of. `user_data_dir` gives the browser a profile that survives across runs, and a session already in that jar takes precedence over anything supplied — which is what lets a profile be seeded once and then run with an empty environment. Chrome locks a profile directory, so `max_workers` is forced to 1 when one is set.

Recovery from a retired session needs **no UI automation at all**: with `li_rm` present, a request to an authenticated route has a fresh session issued silently, so `__recover_session` just navigates to `FEED_URL` and waits. Reproduce the retired state on demand with `driver.delete_cookie('li_at')` on the profile, keeping `li_rm`.

`interactive_login` is the only path that opens a visible browser, it requires `user_data_dir`, and it is off by default because it waits up to 10 minutes for a human — a default that would hang CI. `login.ensure_session` spends one short lived headless browser deciding whether a sign in is needed at all (`has_credentials`: does the profile hold `li_at` or `li_rm`?), which is cheaper than opening a window somebody has to close. It runs in `run()` before any worker starts, because Chrome locks the profile.

Three traps here, each hit once:

- **Never read the cookie jar straight after a navigation.** `page_load_strategy` is `'none'`, so `driver.get` returns before the response carrying the cookie is processed. `__wait_for_session` polls for up to `SESSION_WAIT_TIMEOUT`; checking immediately reported an empty jar on a profile that had a session a second later.
- **`Selectors.appShell` does not match `/feed/`**, whose class names are obfuscated hashes; it matches the jobs pages only. `login.py` waits to be past the sign in pages (`Selectors.signInForm` plus `SIGN_IN_PATHS`) rather than for the shell, which is why it no longer hangs on a good session.
- **A supplied pair must not overwrite a profile's own.** `li_rm` is bound to the `bcookie` it was issued with, so replacing half of a profile's pair with half of somebody else's breaks both. `__authenticate` injects only when the jar holds no `li_rm`.

`__open_results` answers a refusal by emptying the jar of its session and authenticating once more, then retrying the page. This is what makes a fresh credential usable against a profile holding a retired one: the jar is consulted first, so without it a stale profile cookie would keep winning and the run would die with the caller's good cookie never tried. Both of LinkedIn's refusals are treated the same, since the jar proves nothing either way — cookie cleared, or cookie kept and the logged out page served. If the retry gets a session that still renders no results the location is skipped (throttling looks exactly like that); if it gets no session at all, it emits `INVALID_SESSION` and `InvalidCookieException` aborts the run.

**Never read the cookie jar without asking where the browser is.** `driver.get_cookie` returns the jar of the *document on screen*, so on an error page — a network failure, an HTTP 429, which is what LinkedIn answers a fast run with — it reads empty no matter what session the browser holds, and cookies cannot be injected there either (`InvalidCookieDomainException`). Measured: a 429 during pagination made a healthy session look retired, and the recovery then tried to re-inject the pair onto `chrome-error://chromewebdata/`. `__is_session_lost` is the check to use — it is `__is_on_linkedin` **and** no session cookie — and `__wait_for_linkedin` guards every point where a credential is about to be injected. Nothing may conclude "the session is gone" from the cookie alone.

**Recovery also happens mid-run**, not just at the start of a location. The pagination loop, the jobs loop and the pagination-failure path all route back through `__open_results` on the page they are on, instead of warning and carrying on into failures — that is the case a long run meets. Three things hold it together: `MAX_SESSION_RECOVERIES` caps it per location, so "reissued, then refused again" cannot loop; `processed_ids` is scoped to the location, so re-opening a page half way through it does not emit its jobs twice; and pagination questions the session only after failing twice, because a page that will not render is usually just a page that will not render. `INVALID_SESSION` therefore now means *every credential was refused*, where before 6.0.0 it meant *a missing cookie was noticed* — it fires only where `__open_results` gives up. Reproduce any of this with `tests/manual/mid_run_recovery.py`, which monkey-patches the deletion in rather than putting a hook in shipped code; note it deletes `li_rm` alongside `li_at`, since LinkedIn silently mints a replacement while `li_rm` is still in the jar and nothing under test would run.

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
| `on_site_or_remote` | `f_WT` (**only applied when authenticated**, from the `is_authenticated` flag `LinkedinScraper` computes with the same condition that picks the strategy — not from `LI_AT_COOKIE`, which is empty in the remember me modes) |

Adding a filter means: add the enum member with the code copied from a real LinkedIn search URL, add the mapping in `__build_search_url`, add validation in `QueryFilters.validate`, and document it in the README's filter list.

### Option merging and defaults

`Query.merge_options` fills per-query `None` fields from the global `QueryOptions` passed to `run()`, falling back to hardcoded defaults (`limit=25`, `apply_link=False`, `skip_promoted_jobs=False`, `page_offset=0`). If no global options are given, `run()` synthesises `QueryOptions(locations=['Worldwide'], limit=25)`. Pagination is driven by the `start` query param in steps of `PAGINATION_SIZE` (25, LinkedIn's page size); `page_offset` is a page count, not a job count.

### The results list is virtualized — iterate by job id, never by position

This is the single most important invariant. LinkedIn renders only a handful of job cards at a time and removes the rest from the DOM ("occludable" list), so `document.querySelectorAll('div.job-card-container')` returns a *moving subset* of the page, typically 7–12 of 25. Indexing into that NodeList silently reads the wrong job.

Every item of the list, rendered or not, carries `data-occludable-job-id` (`JOB_ID_ATTRIBUTE`). `AuthenticatedStrategy.__get_job_ids` enumerates those ids once per page, and the jobs loop then addresses each job through `get_job_item_selector(job_id)`. `__load_job_card` scrolls an item into view and polls until its card exists before any field is read. Do not reintroduce positional access.

**The first render of a page is not the page.** LinkedIn paints a preliminary list and replaces it about a second later with the real one, and the two do not always hold the same jobs: measured on `start=0`, 7 items appeared at once, and at page time 1053 ms two of them were removed and 20 others added. The two that vanished turned up on `start=25` — the preliminary list is partly made of items belonging to a different page. So ids read from it address items that are about to stop existing, and the run then spent the whole `__load_job_card` timeout on each before reporting a `Timeout on rendering job card` that was not a rendering failure at all.

`__wait_for_stable_job_ids` seeds the jobs loop instead, and it runs at the top of the pagination loop so every page gets it. Costs ~1–2 s per page. **Nothing in the DOM marks the preliminary render**, which was checked rather than assumed: container, `ul` and items carry identical attributes in both (only the Ember ids change, `ember34` → `ember200`, so the list is re-created wholesale), and the loading markers do not clear between them — 53 skeleton nodes at the preliminary render, 31 at the settled one, and `aria-busy` set on the *later* of the two. Size is the one thing that separates them: every preliminary render measured held 7 items where the settled one held `PAGINATION_SIZE`. So the wait requires a full batch *and* `LIST_SETTLE_QUIET_PERIOD` of no change; short of a full batch only `LIST_SETTLE_TIMEOUT` can tell a render still arriving from the last page of results, which genuinely holds fewer.

Treat that wait as an optimisation, not a guarantee — the guarantee is the layer below it.

That is a race the loop must also survive, since LinkedIn can re-render at any point: `__load_job_card` answers `missing` when the item is not in the list at all (after `MISSING_ITEM_GRACE`, so a momentary detachment does not count), the jobs loop skips those ids without touching `metrics.failed`, and only an item that *is* present but never renders a card is a failure. Do not collapse the two answers back into one bool.

The list's own scroll container has a runtime-generated obfuscated class name, so it cannot be selected by class; reach it structurally (walk up from the `ul` to the first scrollable ancestor) if you ever need it directly.

### Extraction is JavaScript, not Selenium

Nearly all field extraction is a `driver.execute_script(...)` call with CSS selectors passed as `arguments[n]`. Selenium's own element API is barely used. Waiting is done with hand-rolled poll loops (`__load_job_card`, `__load_job_details`, `__paginate`) that sleep 50 ms and time out, not `WebDriverWait` (one exception: the initial container wait).

Chrome DevTools Protocol is used directly for things Selenium can't do: `Network.setUserAgentOverride` for the headless masking, and `Target.getTargets` / `Target.closeTarget` to capture the off-site apply URL from the tab LinkedIn opens (`__extract_apply_link`).

`__paginate` waits as long as the initial container wait and reports `__describe_page` when it gives up. Pagination is intermittent — identical configurations have both failed and succeeded — so that dump (status, ready state, container and guest markers, item count, title, URL, leading visible text) is the way into the next failure. It retries once after `PAGINATION_RETRY_DELAY`, but not when the page came back throttled: the backoff below has already waited that out.

### A 429 is readable, and it is the one failure worth waiting through

LinkedIn answers a run that is going too fast with an HTTP 429 carrying **no body**, so Chrome throws the response away and shows its own error page. The browser is then on `chrome-error://chromewebdata/`, where there is no container to wait for, no cookie jar to read, and nothing that names the cause — a 25-job page followed by a dead pagination, which is exactly what it looks like from the log.

The status survives on `performance.getEntriesByType('navigation')[0].responseStatus`, which reports 429 on Chrome's own error page and needs no CDP Network domain (verified against a local server returning 429 with an empty body, and 429 with a body, and 999). `__get_response_status` / `__is_throttled` read it, and `__describe_page` prints it as `status=`.

`__open_and_wait` owns the response: it opens a url, runs the caller's wait, and — **only** when the reply was a 429 — sleeps and asks again, through `THROTTLE_BACKOFF_DELAYS` (5 s, 15 s, 45 s). Every other outcome goes straight back to the caller, so a genuinely unrendered page still fails fast. Those three are a ladder the wait is *drawn around*, not the wait: `jittered_backoff` spreads each step by `THROTTLE_BACKOFF_JITTER` (±50%), so two workers refused in the same moment do not ask again in the same moment. It is deliberately not *full jitter* (`uniform(0, base)`) — a 429 is cleared by time, so a first wait near zero spends the attempt for nothing, and the bounded form decorrelates the workers while keeping the 5/15/45 shape the README describes. Both `__open_results` and `__paginate` go through it, which is what makes a mid-run throttle survivable where before it ended the query with `Couldn't find more jobs`. `tests/manual/throttle_backoff.py` drives all of it against a local server, so none of it needs LinkedIn to be angry.

A successful open is deliberately **not** reported to the pacer as clean work, which is why `__slow_down` is called from both `__observe_resources` and `__open_and_wait` while `__speed_up` is called only from the former. The unit easing is earned in is a job, and jobs vastly outnumber navigations, so counting these too would quietly shorten the run of clean work `CLEAN_RUN_BEFORE_EASING` names.

Throttling and a retired session still look alike, and none of this changes that: `__is_session_lost` remains the check, and a 429 must never be answered by spending a credential.

**A navigation is not the only thing that gets throttled, and it is not even the common case.** Job details are fetched by LinkedIn's own JavaScript rather than navigated to, so a 429 there never reaches `__is_throttled` at all — before this it surfaced as `Timeout on loading job details` and inflated `metrics.failed` with no hint of the cause. `PerformanceResourceTiming.responseStatus` carries it: measured against the live site, all 180 fetch/XHR entries of a three-job run reported a real status and every `www.linkedin.com/voyager/api/…` call among them reported 200, so the calls that matter are same-origin and readable. (About a fifth of the entries report `0` — cross-origin assets with no `Timing-Allow-Origin` — which is harmless, since `0` is never 429.)

`__count_throttled_resources` counts the 429s in that buffer and `__observe_resources` turns the count into a signal by comparing it against the previous reading: a delta means a refusal and an unchanged count means clean work. It runs once per job, in the `finally` of the per-job try, because the failure paths are exactly the ones a throttle leaves through.

**A count is only comparable within one document, and the count cannot say which document it came from.** The buffer belongs to the document and goes away with it, so a reading from a new one is a new baseline and not a verdict on anything — but a fresh document reports `0`, and against a baseline of `0` that is indistinguishable from a document nobody refused anything. So the old count-only comparison voted *clean* on every document swap it met at a zero baseline, easing a pace no work had earned; measured by replaying 20 consecutive swaps through it, the pace eased from 1.0 s to 0.67 s. Both readings therefore carry `performance.timeOrigin`, which is set when the document is created and needs no CDP: a different origin re-baselines silently whatever the counts say, and only within one origin does the delta mean anything. The reading is a `(time_origin, count)` pair everywhere, and the initial baseline is `None` — there is no document yet, and no number could stand for that. A count that goes *down* under an unchanged origin is kept as its own case, silent like a swap: the page cleared its own timings, which says as little about the run as a new document does. The buffer holds 250 entries by default and silently drops the rest, which one page of results fills on its own, so `__open_and_wait` raises it to `RESOURCE_TIMING_BUFFER_SIZE` on every successful open — raising, never `clearResourceTimings()`, which would destroy timing data the page itself may be reading. `__count_throttled_resources` returns `None` rather than `0` when the buffer cannot be read: `0` would look like a reset, re-baseline to nothing, and then report the whole buffer as fresh refusals on the next reading.

**The baseline is a local in `run()` and must stay one.** `LinkedinScraper.__init__` builds one strategy instance and every query thread calls `run()` on it, so anything on `self` is shared by all of them — a per-document counter there would be a new race in a change made to remove one.

### The pace is discovered, not configured

`utils/pacing.py` owns every number involved. `slow_mo` is the **floor** the run never goes below and no longer the pace it keeps; `Pacer` doubles the delay on each refusal up to `min(PACING_CEILING_LIMIT, slow_mo * PACING_CEILING_FACTOR)` and eases it by `PACING_EASE_FACTOR` after `CLEAN_RUN_BEFORE_EASING` jobs nobody refused. Easing is deliberately slower than raising, because the limit looks cumulative and a run should be reluctant to spend the recovery a backoff bought it.

**One pacer per `LinkedinScraper`, shared across its query threads under a lock.** The limit is enforced per account, so a 429 one worker meets is a reason for all of them to slow down. This is the opposite of the baseline above, and for the opposite reason: that counter belongs to a document, this one to an account.

`slow_mo` below `MIN_SLOW_MO` (0.2) raises at construction — a breaking change against 6.0.0's own unreleased state, taken because `0` produced a ceiling of `min(10, 0) = 0` and switched the whole mechanism off silently. With that minimum the ceiling is never below 2 s, so an enabled pacer always has room to move and there is no configuration where `adaptive_slow_mo=True` does nothing. `adaptive_slow_mo=False` builds a pacer whose ceiling equals its floor, which makes `min(delay * factor, ceiling)` inert without a special case anywhere — the sleep sites read `scraper.pacer.delay` either way, and `scraper.slow_mo` stays public and stays the number the caller asked for. `AnonymousStrategy` reads the pacer too, though nothing on that path can raise it, so there is one notion of how fast a run goes instead of two.

`EventMetrics` carries `throttled` (429s seen) and `pace` (what is being slept now). The count is kept even on an inert pacer, so the two modes stay comparable.

`tests/manual/throttle_backoff.py` covers all of this too — the pacer with no browser at all, the constructor validation, a throttled navigation raising the pace once per attempt, and a page that fetches one refused and one served resource — so none of it needs LinkedIn to be angry.

### Selectors are the fragile surface

Each strategy declares a `Selectors` class at the top of its module. This is where breakage concentrates when LinkedIn ships a UI change, and the git history is mostly selector fixes. "Promoted" detection matches the literal string `'Promoted'` in a list item, so it is locale-dependent (the driver forces `--lang=en-GB` for this reason).

`date_text` reads `…top-card__tertiary-description-container`, whose text is `<place> · <date> · <applicants>` with any segment possibly absent; the date is matched by shape (`/\bago\b|just now/i`) rather than by position, because positional selectors on this node break whenever a segment is missing.

Job "insights" (on-site/remote, contract type, skill-match summary) are `<button>` elements inside `.job-details-fit-level-preferences`, not list items.

LinkedIn no longer exposes required-skill names anywhere in the DOM — only a Premium-gated "N of M skills match" control — so `EventData` has no `skills` field. Do not add one back without checking the live DOM first.

The strategy also defensively dismisses UI that blocks scraping on every pagination round: `__accept_cookies`, `__dismiss_global_alert`, `__close_chat_panel`. `__dismiss_global_alert` clicks `button.artdeco-global-alert__dismiss` by selector, deliberately not by button text, so it works regardless of locale.

### Events

`LinkedinScraper` is a small event emitter (`on` / `once` / `emit` / `remove_listener`). Callback arity is validated at registration: `DATA`, `ERROR`, `METRICS`, `SESSION_REFRESHED` take exactly one argument; `END` and `INVALID_SESSION` take zero. Only `FunctionType` values pass the `isinstance` check, so plain functions and lambdas work but bound methods and callable objects are rejected.

`SESSION_REFRESHED` carries an `EventSession` and fires when the cookie the browser ends up holding differs from `Config.LI_AT_COOKIE`, so a caller with no persistent profile can store it for the next run.

An exception raised inside a user callback is wrapped as `CallbackException` and re-raised out of `run()`, aborting the scrape. `InvalidCookieException` propagates the same way. Every other exception is swallowed and re-emitted as an `ERROR` event so the run continues. `END` is emitted per query thread, not once per `run()`.

`EventData` is a `NamedTuple`; adding or removing a field means also updating the README's field list and `tests/shared.py`. Note that `x in data` on a `NamedTuple` tests *values*, not field names — never use it to probe for a field's presence.

### Tuning knobs that matter

`slow_mo` (the floor on seconds slept between jobs, see *The pace is discovered*) and `max_workers` exist to avoid HTTP 429. The README recommends `slow_mo >= 0.5` and a single worker in authenticated mode. Increasing default concurrency is a behavioural regression, not an optimisation.

## Gotchas

- Logging goes through `utils/logger.py` to the `li:scraper` namespace; level comes from the `LOG_LEVEL` env var (read at import time). `logger.py` truncates each argument at 1000 chars.
- `tests/manual/validate_fields.py` needs `PYTHONPATH` set to the directory holding the package (`/app` in the container). Running a file by path puts *its own* directory on `sys.path`, not the working directory, so without it the import of `linkedin_jobs_scraper` fails.
- There is no proxy support. A dead, broken proxy API used to exist on `LinkedinScraper` and in `chrome_driver.py`; it was removed in 6.0.0. Adding real proxy support means wiring `--proxy-server` into `get_default_driver_options`, not restoring the old shape.
- `tmp/` is gitignored scratch space holding downloaded Chrome/chromedriver builds — not part of the package.
- Chrome/chromedriver version compatibility is the most common source of local-only failures, and Selenium Manager will *not* rescue a mismatched driver already on `PATH` — it warns and then fails with `SessionNotCreatedException`. `chrome_executable_path` (chromedriver) and `chrome_binary_location` (Chrome/Chromium binary) let a caller pin a matched pair; running with `PATH="/usr/bin:/bin"` hides the stray driver and lets Selenium Manager fetch a matching one.
