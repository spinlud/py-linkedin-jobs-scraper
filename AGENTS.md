# AGENTS.md

`linkedin-jobs-scraper`: a PyPI package that scrapes LinkedIn job postings through an authenticated headless Chrome driven by Selenium, with a CLI (`lijs`, `linkedin-jobs-scraper`, `python -m linkedin_jobs_scraper`; subcommands `jobs` / `job` / `login`). A sibling npm package aims for feature parity.

## Working here

- Environment: uv (`pyproject.toml`, `uv.lock` committed, Python pinned in `.python-version`). The `package.json` scripts are the entry points: `npm run test` is the offline unit suite (`tests/unit/`, the only suite CI runs).
- **Live suites hit the real LinkedIn site**: `npm run test:e2e` (`tests/test_programmatic.py`, `tests/test_cli.py`; `tests/shared.py` holds the `EventData` shape assertions). Authenticate with `LI_CHROME_USER_DATA_DIR=~/.lijs/chrome-profile` (a profile seeded by `lijs login`) or the `LI_RM_COOKIE` + `LI_BCOOKIE` pair. Chrome locks a profile, so run one browser at a time. A failing live test usually means LinkedIn changed its DOM.
- **Every search moves the account's remembered location** to its own. After live work, run one search on the account's usual location to put it back.
- `.githooks/pre-commit` (enabled by `npm run hooks`) bumps the patch version on every commit; `git commit --no-verify` skips it. The version lives only in `pyproject.toml`.
- **A push to `master` publishes to PyPI.** Push there only when the maintainer asks.
- `tests/manual/` holds standalone probes; run them with `PYTHONPATH=.`.
- `docs/` and `tmp/` are gitignored scratch space.

## Architecture

`LinkedinScraper.run(queries)` runs one thread per `Query`, each with **one Chrome driver** reused across its locations, all delegating to the single `AuthenticatedStrategy` built in the constructor. Anything stored on the strategy instance is shared by every thread, so per-run state stays in locals. The CLI under `cli/` (`args` → `mapping` → `main`, with `output` and `events` for stdout/stderr) mirrors the library for one query per invocation.

`Config` reads the environment at import time.

### The driver must not look automated

`get_default_driver_options` drops `--enable-automation` and sets `--user-agent` at launch to the browser's own User-Agent minus the `HeadlessChrome` token (`resolve_masked_user_agent`, derived from the running browser, never hardcoded). `mask_headless_user_agent` does the same over CDP when the caller supplies `chrome_options`; it passes `userAgentMetadata` and leaves `acceptLanguage` out (Chrome would malform the header). `--disable-web-security` stays out: with a profile it is detectable.

### Sessions

The session source is resolved once (`utils/session_source.py`): an explicit profile, else cookie env vars, else the default profile `~/.lijs/chrome-profile`. A missing or empty profile with no cookie to seed it raises `InvalidCookieException` before any browser opens; only `login` creates profiles.

- **The remember-me pair** (`li_rm` + `bcookie`) is the durable credential: LinkedIn mints a fresh `li_at` from it on any authenticated route, so recovery is a navigation, never UI automation. Only a pair produced by `lijs login` works; one copied from an everyday browser is refused. An injected pair carries an expiry (`REMEMBER_COOKIE_MAX_AGE`), and a profile's own `li_rm` is never overwritten.
- `li_at` alone works but retires after ~100 job loads.
- `page_load_strategy` is `'none'` and `get_cookie` reads the jar of the document on screen, so a session is judged lost only by `__is_session_lost` (on LinkedIn **and** no session cookie), after waiting (`__wait_for_session`).
- `__open_results` answers a refusal by clearing the session cookie, authenticating once more and retrying; mid-run recoveries route through it, capped by `MAX_SESSION_RECOVERIES`. `INVALID_SESSION` fires only when no usable session remains.

### Throttling and pace

A 429 arrives bodiless, as Chrome's error page; `performance.getEntriesByType('navigation')[0].responseStatus` still reads it. `__open_and_wait` retries only a 429, through the jittered `THROTTLE_BACKOFF_DELAYS` (LinkedIn sends no `Retry-After`, measured). Detail fetches are throttled without a navigation, so `__observe_resources` counts 429s in the resource-timing buffer per document, keyed by `performance.timeOrigin`.

`utils/pacing.py`: `slow_mo` (default 0.8, minimum 0.2) is a floor; one `Pacer` per scraper, shared under a lock, doubles on refusals and eases slowly after clean jobs. `max_workers` defaults to 1; keep both defaults.

### Search URL and locations

Searches go to `/jobs/search-results/` (`__build_search_url`). A location is a `geoId`: a `Location` or a numeric string as is; any other name is resolved through the page's own location picker (`utils/location_picker.py`, cached per process, typeahead endpoint never called directly). No location sends no `geoId`, which searches the account's remembered location. The new page has **no Worldwide search**, so an explicit `'Worldwide'` is warned and skipped. The applied location is read back from the `Location <name>` control as `resolved_location`; a picker-resolved name that LinkedIn did not apply is re-opened once, then skipped. A search needs keywords: without them the page shows suggestions, never results.

Filters are URL params whose values are LinkedIn's codes, kept in `filters/filters.py`. Workplace, experience and employment type share one `f_SAL` param: `f_SA_id_<facet>:<v>,<v>` sections joined by `$` (`__f_sal`). New codes are captured from a real browser URL and verified live by comparing the result cards. Adding a filter touches the enum, `__build_search_url`, `QueryFilters.validate`, the CLI flag (`cli/args.py`, `cli/mapping.py`) and the README filter list.

### The results page

- **Address every job by id.** Cards carry `componentkey="job-card-component-ref-<jobId>"`; the list streams in and re-renders, so a position is never a job. `__wait_for_stable_job_ids` waits for the list to settle; `__load_job_card` answers `missing` (skipped, not a failure) apart from a card that never renders (a failure).
- **JS collects, Python interprets.** In-page scripts return raw texts, hrefs and aria-labels; `utils/job_record.py` parses them into `EventData`, unit-tested with strings captured live. Detail reading is scoped by the job's own `JobDetails_*_<jobId>` components and shared by search and `scrape_job` (`/jobs/view/<id>/`).
- **Selectors are the fragile surface.** Class names are generated, so anchor on semantic `componentkey` values, `data-testid`, `aria-label` ("Location <name>", "Easy Apply to this job", "Apply on company website"), `href` paths (`/company/<slug>/`, `/safety/go/?url=`) and text shapes. "Promoted" and "Easy Apply" are matched in English; the driver forces `--lang=en-GB` for that.

## Events

`LinkedinScraper` is a small event emitter; callback arity is validated at registration. `BEGIN` (`EventBegin`: `total`, `total_capped`, `location`, `resolved_location`) fires once per location that is scraped; a skipped location fires none. An exception in a user callback is re-raised as `CallbackException`; `InvalidCookieException` propagates; everything else becomes an `ERROR` event. Adding or removing an `EventData` field means updating the README field list and `tests/shared.py`. `x in data` on a `NamedTuple` tests values, not field names.

## Gotchas

- Logging: the `utils/logger.py` helpers (`debug`/`info`/`warn`/`error`) join their arguments with tabs and log with `stacklevel=2`; call them directly. The library installs no handler; the CLI attaches one for `-v` / `-vv` / `LOG_LEVEL`.
- Without `chrome_executable_path`, Selenium Manager supplies a chromedriver matching the installed Chrome and a chromedriver on `PATH` is ignored.
- There is no proxy support; adding it means wiring `--proxy-server` into `get_default_driver_options`.
