# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`linkedin-jobs-scraper`: a PyPI package that scrapes public LinkedIn job postings by driving a headless Chrome instance through Selenium. There is a sibling npm package (`linkedin-jobs-scraper`) with equivalent behaviour — feature parity between the two is intentional.

## Commands

The project uses [uv](https://docs.astral.sh/uv/) for the environment and packaging; `pyproject.toml` (hatchling backend, PEP 621) declares dependencies and metadata, `.python-version` pins the local interpreter to 3.13, and `uv.lock` is committed. `uv run` and `uv sync` provision the env from those on demand, so there is no separate install step. The `package.json` scripts are the canonical entry points and wrap uv:

```shell
npm run hooks    # git config core.hooksPath .githooks (once per clone)
npm run test     # uv run pytest tests/unit --capture=no --log-cli-level=DEBUG (offline unit suite)
npm run clean    # remove build/, dist/, *.egg-info, __pycache__, .pytest_cache
npm run build    # clean + uv build (sdist + wheel into dist/)
npm run deploy   # uv publish to testpypi

npm run test:e2e:programmatic   # live programmatic suite (needs credentials)
npm run test:e2e:cli            # live CLI suite (needs credentials)
npm run test:e2e                # both live suites
```

`.githooks/pre-commit` bumps the patch version in `pyproject.toml` and stages it, so every commit carries its own version. Git never enables a cloned repository's hooks on its own, so `npm run hooks` (or the `git config` behind it) is needed once per clone; `git commit --no-verify` skips it for a single commit. It stands down while git is replaying commits that already carry a version — merge, rebase, cherry-pick, revert — and when `pyproject.toml` holds unstaged changes, which staging the bump would sweep into the commit.

The cost is structural, not a defect: every commit touches the same line, so branches that diverge collide on it, and a cherry-pick across them stops on a conflict in `pyproject.toml`. Versions also count commits rather than releases. Bumping on push to `master`, or deriving the version from a git tag, are the two ways out if that becomes tiresome.

Running the live suites directly (CI runs only the offline unit tests under `tests/unit/`; the live suites below are run locally before merging to `master`). The `npm run test:e2e:*` scripts above wrap these; run them directly to pass a credential inline:

```shell
LI_RM_COOKIE=<li_rm> LI_BCOOKIE=<bcookie> uv run pytest tests/test_programmatic.py::test_run   # programmatic live suite
LI_RM_COOKIE=<li_rm> LI_BCOOKIE=<bcookie> uv run pytest tests/test_cli.py                       # CLI live suite
```

`LI_CHROME_USER_DATA_DIR=<path>` is an alternative to the cookie pair for both live suites: point a run at a seeded Chrome profile that already holds a session (the `login` subcommand produces one) and no env cookies are needed. The suites pass it through — to `LinkedinScraper(chrome_user_data_dir=...)` and to the CLI's `--chrome-profile` (alias `--chrome-user-data-dir`) — and the "profile wins" logic authenticates from the profile's own session.

Selenium Manager fetches a chromedriver matching the local Chrome, so there is nothing to install; a chromedriver on `PATH` is ignored (see *Gotchas*).

**The live suites hit the real LinkedIn site.** Two of them, run locally rather than in CI: `tests/test_programmatic.py` drives the library in-process (`tests/shared.py` asserts on the shape of each emitted `EventData`), and `tests/test_cli.py` runs the CLI as a subprocess and asserts on its exit codes and jsonl stdout. Both need no fixtures and take a credential from the environment — use the remember me pair rather than `LI_AT_COOKIE`, which each suite exhausts in about two runs. A failing live test usually means LinkedIn changed its DOM (see *Selectors*), not that the Python logic broke. Offline unit tests live under `tests/unit/` and need no credential.

`tests/manual/` holds standalone probes that need no live LinkedIn: `throttle_backoff.py` (backoff ladder and pacer, against a local server), `mid_run_recovery.py`, `remote_probe.py`, `network_headers_probe.py`, `validate_fields.py`.

Release: pushing to `master` publishes to PyPI via `.github/workflows/ci.yml`. Version is declared only in `pyproject.toml` (`package.json`'s version is unused). Because a push to `master` publishes, never push there without the maintainer explicitly asking.

## Architecture

Flow: `LinkedinScraper.run(queries)` → one `ThreadPoolExecutor` task per `Query` → **one Chrome driver per task**, reused across the loop over `query.options.locations`, delegating to `AuthenticatedStrategy`. One browser per query rather than per location, because every new browser is another session establishment for LinkedIn to look at.

A CLI wraps this API: console scripts `linkedin-jobs-scraper` and `lijs`, plus `python -m linkedin_jobs_scraper`, with subcommands `jobs` / `job` / `login`. It lives under `linkedin_jobs_scraper/cli/` (`args` parses argv into a typed `CliConfig`, `mapping` turns kebab strings into filter/domain objects, `output` writes table/jsonl/json/csv, `events` turns scraper events into stderr feedback and exit codes, `main` orchestrates). It mirrors the programmatic API but runs a single query per invocation and exposes no `max_workers` or `chrome_options`. Credentials come from the environment or a Chrome profile (`--chrome-profile`, default `~/.lijs/chrome-profile`); `login` signs a profile in and prints the cookie pair.

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

`LinkedinScraper.__init__` builds `AuthenticatedStrategy` unconditionally and every query thread calls `run()` on that one instance. The constructor cannot see whether a session exists — a profile carries its own — so `__authenticate` holds the verdict until a browser is open.

The constructor does pick the **session source**, in `utils/session_source.py` (`resolve_session_source`), the same for CLI and library: an explicit profile (`chrome_user_data_dir`, or `--user-data-dir` in the caller's `chrome_options`) first; else cookie mode when the environment holds a usable credential (`LI_AT_COOKIE`, or `LI_RM_COOKIE` with `LI_BCOOKIE`; a lone half does not count); else `DEFAULT_CHROME_PROFILE` (`~/.lijs/chrome-profile`), treated exactly like an explicit profile. `run()` / `scrape_job()` log the choice once at INFO (the CLI also prints `SessionSource.summary()` on the `session` row of its pre-run summary) and, when the profile, default or explicit, is missing or empty and no cookie credential is in the environment to seed it, emit `INVALID_SESSION` and raise `InvalidCookieException` (`missing_session_message`) before any browser opens, so the CLI exits 2 and prints the message as `error: ...` — scraping never creates it; only `login.sign_in` / `ensure_session` do, owner-only (`create_profile_dir`, 0o700 on every directory it creates, pre-existing ones untouched). `sign_in` removes the directories that call created (`remove_created_profile_dirs`, after quitting the browser) whenever it ends without a session — timeout, closed browser, exception or `KeyboardInterrupt` — and never a directory that existed before it; `lijs login` maps Ctrl-C to exit code 130. `build_driver` adds the profile to caller `chrome_options` that name no `--user-data-dir` of their own.

A browser that starts without a session and gets none from the source (an empty or expired profile, no cookie, a refused cookie) is handled by `__require_session` before the first page: it emits `INVALID_SESSION` and raises `InvalidCookieException`, which aborts the run; the CLI exits 2. That, `__open_results` and the missing/empty profile check in `LinkedinScraper.__prepare_session` are the only places that emit `INVALID_SESSION` or raise `InvalidCookieException`. A failed `interactive_login` sign in raises `RuntimeError` instead (exit 1).

Every `Config` value is read from the environment **at import time** (`config.py`), so setting `os.environ` after importing the package has no effect.

`strategies/strategy.py` stays as the `run(driver, search_url, query, location, page_offset)` contract and the type `self._strategy` is annotated with. `AnonymousStrategy` was removed in 6.0.0; do not add a second strategy back for the no-credential case, because there is nothing to scrape without a credential.

### Two credentials, and they are not equivalent

`AuthenticatedStrategy.__authenticate` prefers the first:

- **The remember me pair**, `LI_RM_COOKIE` + `LI_BCOOKIE` (`li_rm` and `bcookie`). LinkedIn mints a fresh `li_at` for it on any authenticated route. It lasts a year and renews itself, so it is the path both documented modes end up on.
- **`LI_AT_COOKIE`**, a session cookie handed over as is. Nothing can renew it and LinkedIn retires it after roughly a hundred job loads.

Rules for the pair:

- It is the pair and nothing smaller: `li_rm` alone is refused, and so is `li_rm` next to a different browser's browser id.
- **A pair copied out of an everyday browser is refused** — the mechanism is unknown, but it is the credential and not the machine, the browser or the account. The `linkedin-jobs-scraper login` subcommand is the only supported source, and the README must not tell anyone to use devtools for it. `li_at` on its own is unaffected and still copyable.
- An injected pair **must carry an expiry** (`REMEMBER_COOKIE_MAX_AGE`). `add_cookie` without one creates a session cookie Chrome discards on exit, leaving a profile holding a session and nothing able to renew it.
- `bcookie` is not `HttpOnly` and lives on `.linkedin.com`, not `.www.linkedin.com` like the other two.

### Sessions: the profile wins

`utils/session.py` owns the cookies a session is made of. `chrome_user_data_dir` gives the browser a profile that survives across runs, and a session already in that jar takes precedence over anything supplied, which is what lets a profile be seeded once and then run with an empty environment. Chrome locks a profile directory, so `max_workers` (default 1) is forced back to 1, with a warning, when a caller asks for more on a profile, explicit or default; cookie mode honours it.

Recovery from a retired session needs **no UI automation**: with `li_rm` present, a request to an authenticated route has a fresh session issued silently, so `__recover_session` navigates to `FEED_URL` and waits.

`interactive_login` is the only path that opens a visible browser, requires a profile (explicit or default, so it is refused in cookie mode), and is off by default because it waits up to 10 minutes for a human. `login.ensure_session` spends one short lived headless browser deciding whether a sign in is needed at all (`has_credentials`), and runs in `run()` before any worker starts, because Chrome locks the profile.

Three traps:

- **Never read the cookie jar straight after a navigation.** `page_load_strategy` is `'none'`, so `driver.get` returns before the response carrying the cookie is processed. `__wait_for_session` polls for up to `SESSION_WAIT_TIMEOUT`.
- **Never read the cookie jar without asking where the browser is.** `driver.get_cookie` returns the jar of the *document on screen*, so on an error page — a network failure, an HTTP 429 — it reads empty whatever session the browser holds, and cookies cannot be injected there either (`InvalidCookieDomainException`). `__is_session_lost` is the check to use: `__is_on_linkedin` **and** no session cookie. `__wait_for_linkedin` guards every point where a credential is about to be injected. Nothing may conclude "the session is gone" from the cookie alone.
- **A supplied pair must not overwrite a profile's own.** `li_rm` is bound to the `bcookie` it was issued with, so replacing half of a profile's pair with half of somebody else's breaks both. `__authenticate` injects only when the jar holds no `li_rm`.

`__open_results` answers a refusal by emptying the jar of its session, authenticating once more and retrying the page — which is what makes a fresh credential usable against a profile holding a retired one. Both of LinkedIn's refusals are treated the same, since the jar proves nothing either way. If the retry gets a session that still renders no results the location is skipped (throttling looks exactly like that); if it gets no session at all, it emits `INVALID_SESSION` and `InvalidCookieException` aborts the run.

**Recovery also happens mid-run.** The pagination loop, the jobs loop and the pagination-failure path all route back through `__open_results` on the page they are on. Three things hold it together: `MAX_SESSION_RECOVERIES` caps it per location, so "reissued, then refused again" cannot loop; `processed_ids` is scoped to the location, so re-opening a page half way through it does not emit its jobs twice; and pagination questions the session only after failing twice, because a page that will not render is usually just a page that will not render. `INVALID_SESSION` therefore means *no usable session*: every credential was refused, or there was none to begin with, and fires only where `__open_results` gives up, `__require_session` finds nothing to authenticate with, or `__prepare_session` finds the profile missing or empty with no cookie to seed it.

`tests/manual/mid_run_recovery.py` reproduces all of it, monkey-patching the deletion in rather than putting a hook in shipped code. It deletes `li_rm` alongside `li_at`, since LinkedIn silently mints a replacement while `li_rm` is still in the jar.

### Search URLs: always a geoId, filters as URL params

`LinkedinScraper.__build_search_url` targets `JOBS_SEARCH_RESULTS_URL` (`/jobs/search-results/`). Every URL carries an explicit `geoId`, because **LinkedIn remembers the last searched location per account** and a search without one inherits it; no location means Worldwide, `WORLDWIDE_GEO_ID` (`92000000`). A free-text `location=` is never emitted: LinkedIn drops it. The side effect cuts the other way too: any search, a manual one included, leaves the account's remembered location at its `geoId`, so put the account back where you found it after live work.

`Query.validate` refuses a query without keywords: the page answers one with a landing page of suggested searches, never results, a company-only search included.

Enum values in `filters/filters.py` *are* LinkedIn's own codes:

| Filter | Param |
| --- | --- |
| `company_jobs_url` (extracts `f_C`) / `company_id` | `f_C` |
| `time` | `f_TPR` |
| `easy_apply` | `f_AL=true` |
| `under_10_applicants` | `f_EA=true` |
| `verified` | `f_VJ=true` |
| `on_site_or_remote`, `experience`, `type` | `f_SAL` |

`f_SAL` packs three facets into one param: values comma-separated within a section, sections joined with `$`, always in the order workplace, experience, employment type (`__f_sal`):

```
f_SAL = f_SA_id_225001:272001,1621001$f_SA_id_227001:277001$f_SA_id_226001:272015
```

| Section | Facet | Values |
| --- | --- | --- |
| Workplace (`OnSiteOrRemoteFilters`) | `225001` | On-site `296001`, Remote `272001`, Hybrid `1621001` |
| Experience (`ExperienceLevelFilters`) | `227001` | Entry-level `276001`, Senior `277001`, Manager `278001`, Director `272003`, Executive `279001` |
| Employment type (`TypeFilters`) | `226001` | Full-time `272015`, Part-time `273001`, Contract `274001`, Internship `275001`, Volunteer `272002` |

The codes are global, not per search. The filter dialog's inputs carry no codes (every value is `on`, and scripted clicks do not update its "Show results" link), so a code is captured from a real browser session and verified by loading the URL: compare the cards' workplace, title and employment labels with and without it.

LinkedIn drops `sortBy`, `f_SB2`, `f_I`, `f_F`, `f_BE`, `f_JC`, `f_JT`, `f_E` and `f_WT`; they were removed in 9.0.0 and do not come back through keywords or any other workaround. "In my network" is unimplemented because its encoding could not be observed on an account without connections.

Adding a filter means: the enum member or param with a code verified as above, the mapping in `__build_search_url`, validation in `QueryFilters.validate`, the CLI flag in `cli/args.py` / `cli/mapping.py`, and the README's filter list.

### Location names go through the page's own picker

A `Location` or a numeric string is a `geoId` as is. Any other name raises `UnresolvedLocationError` in `__build_search_url`, which `__run` answers with `AuthenticatedStrategy.resolve_location`: it opens a Worldwide search (the picker lives on the search page), and `utils/location_picker.py::pick_location` clicks the `[aria-label^="Location "]` control with a pointer click (`ActionChains`; a scripted click does not open it), types into the contenteditable `LocationTypeahead_TextEditor`, and reads the first href in `semanticSearchBoxLocationList` whose `origin` is `JOB_SEARCH_PAGE_LOCATION_AUTOCOMPLETE`. Before anything is typed the same list holds the account's recent locations (`..._HISTORY`) and LinkedIn's picks (`..._SUGGESTION`), which is why the origin is checked. Nothing is clicked in the list, so resolution searches nothing.

`LOCATION_CACHE` holds matches and misses per process; a picker that could not be operated is not cached. The match is logged at INFO; a miss is warned and the location skipped while the others run. LinkedIn's typeahead endpoint is a React Server Components action with an opaque body that a replay answers with HTTP 500; it stays uncalled.

### Option merging and defaults

`Query.merge_options` fills per-query `None` fields from the global `QueryOptions` passed to `run()`, falling back to hardcoded defaults (`limit=25`, `apply_link=False`, `skip_promoted_jobs=False`, `page_offset=0`). If no global options are given, `run()` synthesises `QueryOptions(locations=['Worldwide'], limit=25)`. Pagination is driven by the `start` query param in steps of `PAGINATION_SIZE` (25, LinkedIn's page size); `page_offset` is a page count, not a job count.

### The results list: address every job by id

The page's class names are generated at build time, so nothing is selected by class. Each card is a `[role="button"]` carrying `componentkey="job-card-component-ref-<jobId>"` (`JOB_CARD_KEY_PREFIX`, `get_job_card_selector`); `__get_job_ids` reads the ids off those keys (a card nests a second element with the same key, hence the de-duplication), and the jobs loop addresses each job through its id. Positional access stays out: the list is streamed and re-rendered, so a NodeList index is not a job.

A page renders all 25 cards at once, but they stream in, so `__wait_for_stable_job_ids` believes a full batch (`PAGINATION_SIZE`) only after `LIST_SETTLE_QUIET_PERIOD` without change, falling back to `LIST_SETTLE_TIMEOUT` for the last page of results, which genuinely holds fewer. It seeds the jobs loop and runs at the top of the pagination loop.

The guarantee is the layer below that wait: `__load_job_card` answers `missing` when the card is not on the page at all (after `MISSING_ITEM_GRACE`), and the jobs loop skips those ids without touching `metrics.failed`. Only a card that *is* present but never renders is a failure. Keep the two answers distinct.

A card is opened by clicking it, which puts `currentJobId` in the URL and fills the detail panel; `__read_job_details` waits for that job's `JobDetails_AboutTheJob_<jobId>` component. Pagination is the `start` param, equivalent to the page buttons. The results count reads "N results" or "N+ results" (`total` / `total_capped` on `EventBegin`).

### Extraction is JavaScript, not Selenium

Nearly all field extraction is a `driver.execute_script(...)` call with CSS selectors passed as `arguments[n]`. Selenium's own element API is barely used. Waiting is done with hand-rolled poll loops (`__load_job_card`, `__read_job_details`, `__paginate`) that sleep 50 ms and time out, not `WebDriverWait` (one exception: the initial container wait).

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

`slow_mo` defaults to `0.8` and `max_workers` to `1`, a single worker, as the README recommends. Increasing default concurrency, or lowering that default, is a behavioural regression, not an optimisation.

### Selectors are the fragile surface

This is where breakage concentrates when LinkedIn ships a UI change. Anchor only on what has proved stable on the new page:

- `componentkey` values with a semantic prefix: `job-card-component-ref-<jobId>`, `JobDetails_AboutTheJob_<jobId>`, `JobDetails_AboutTheCompany_<jobId>`, `semanticSearchBoxLocationList`, `LocationTypeahead_TextEditor`.
- `data-testid` values: `lazy-column`, `primary-nav` (`Selectors.appShell`), `expandable-text-box`, `pagination-indicator-N`, `pagination-controls-*`, `interop-shadowdom`.
- `aria-label` values: "Location <name>", "Easy Apply to this job", "Apply on company website", "View company: <name>".
- Text shapes: relative dates, "N results", "N applicants", "people clicked apply", and the single job page's "Job id provided may not be valid…" (`JOB_NOT_FOUND_TEXT`).

**JS collects, Python interprets.** `READ_JOB_CARD_SCRIPT` and `READ_JOB_DETAILS_SCRIPT` return raw texts, hrefs and aria-labels; `utils/job_record.py` (`parse_job_record`, `parse_job_details`) turns them into `EventData` fields, and its unit tests use strings captured from the live page. Parsing changes belong there, tested offline. The detail script scopes everything by the job's own id, because the single job page (`/jobs/view/<id>/`) also renders similar jobs and other panels: the top card is whatever precedes "About the job" in its `lazy-column`.

- The top line is `<place> · <date> · <applicants>` with an optional "Reposted" prefix and any segment possibly absent, so segments are matched by shape, not position.
- "Promoted" and "Easy Apply" are matched as literal English strings, so they are locale-dependent; the driver forces `--lang=en-GB` for this reason.
- The external apply control is sometimes an anchor with a `/safety/go/?url=<target>` href (decoded in Python) and sometimes a plain button, for which `__extract_apply_link` captures the tab LinkedIn opens.
- `benefits` comes from the card's pill only; a "+N benefits" remainder is dropped and a count-only pill yields `[]`.
- LinkedIn exposes no required-skill names, only a Premium-gated "N of M skills match", so `EventData` has no `skills` field.
- `Selectors.appShell` does not match `/feed/`; `login.py` waits to be past the sign in pages (`Selectors.signInForm` plus `SIGN_IN_PATHS`) instead.

The strategy also dismisses UI that blocks scraping on every pagination round: `__accept_cookies`, `__dismiss_global_alert`, `__close_chat_panel`. `__dismiss_global_alert` clicks `button.artdeco-global-alert__dismiss` by selector, not by button text, so it works regardless of locale.

### Events

`LinkedinScraper` is a small event emitter (`on` / `once` / `emit` / `remove_listener`). Callback arity is validated at registration: `DATA`, `ERROR`, `METRICS`, `SESSION_REFRESHED`, `NOT_FOUND` take exactly one argument; `END` and `INVALID_SESSION` take zero. Any callable is accepted — plain functions, lambdas, bound methods, `functools.partial`, and callable objects — while a non-callable is rejected with a `ValueError`. The per-event arity validation is unchanged: `signature(cb).parameters` is counted (with `self` and any bound `partial` args excluded), so a callback registered for the wrong arity still raises.

`SESSION_REFRESHED` carries an `EventSession` and fires when the cookie the browser ends up holding differs from `Config.LI_AT_COOKIE`, so a caller with no persistent profile can store it for the next run.

`NOT_FOUND` carries an `EventNotFound` and fires when a single-job scrape (`scrape_job`) targets a job that does not exist or is no longer available. It is distinguished from throttling and page-load failures, which stay a silent skip because they say nothing about whether the job exists.

An exception raised inside a user callback is wrapped as `CallbackException` and re-raised out of `run()`, aborting the scrape. `InvalidCookieException` propagates the same way. Every other exception is swallowed and re-emitted as an `ERROR` event so the run continues. `END` is emitted per query thread, not once per `run()`.

`EventData` is a `NamedTuple`; adding or removing a field means also updating the README's field list and `tests/shared.py`. Note that `x in data` on a `NamedTuple` tests *values*, not field names — never use it to probe for a field's presence.

## Gotchas

- Logging goes through `utils/logger.py` to the `li:scraper` namespace; level comes from the `LOG_LEVEL` env var (read at import time). The helpers (`debug`/`info`/`warn`/`error`) join their arguments with tabs into one preformatted message (never `%`-style args), truncate each argument at 1000 chars, and log with `stacklevel=2` so records point at the caller; call them directly, not through another wrapper.
- `tests/manual/validate_fields.py` needs `PYTHONPATH` set to the directory holding the package. Running a file by path puts *its own* directory on `sys.path`, not the working directory, so without it the import of `linkedin_jobs_scraper` fails.
- There is no proxy support. A dead, broken proxy API was removed in 6.0.0; adding real support means wiring `--proxy-server` into `get_default_driver_options`, not restoring the old shape.
- `docs/` and `tmp/` are gitignored scratch space, not part of the package.
- Without `chrome_executable_path`, `utils/chrome_driver.py::resolve_chromedriver_paths` asks Selenium Manager for a chromedriver matching the installed Chrome (or `chrome_binary_location`) with `--skip-driver-in-path`, so a stale chromedriver on `PATH` (e.g. Homebrew's) cannot cause a `SessionNotCreatedException`. Both launch points, `build_driver` and `resolve_masked_user_agent`, go through it. When Selenium Manager cannot provide the driver (e.g. offline with an empty `~/.cache/selenium`) it raises `ChromedriverResolutionException`. An explicit `chrome_executable_path` is used verbatim, with no version check and no Selenium Manager call.
