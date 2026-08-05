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

Running tests directly (requires local Chrome + chromedriver on PATH):

```shell
LI_AT_COOKIE=<cookie> pytest --capture=no --log-cli-level=DEBUG
LI_AT_COOKIE=<cookie> pytest tests/test_.py::test_run   # the only test
```

Running tests in the CI-equivalent container (uses the `spinlud/python3-selenium-chrome` image, which ships a matched Chrome/chromedriver pair — the reliable way to test when the local pair is mismatched):

```shell
LI_AT_COOKIE=<cookie> tests/run_tests.sh
```

**Tests hit the live LinkedIn site.** There are no unit tests and no fixtures — `tests/test_.py` runs real queries and `tests/shared.py` asserts on the shape of each emitted `EventData`. A failing test usually means LinkedIn changed its DOM (see *Selectors* below), not that the Python logic broke. `LI_AT_COOKIE` is required; without it the scraper falls back to the unmaintained anonymous strategy and the test will produce nothing.

Release: pushing to `master` publishes to PyPI via `.github/workflows/ci.yml`. Version is declared only in `setup.py` (`package.json`'s version is unused). Because a push to `master` publishes, never push there without the maintainer explicitly asking.

The base image is built from the separate [spinlud/python3-selenium-chrome](https://github.com/spinlud/python3-selenium-chrome) repo, whose Dockerfile installs Chrome and chromedriver together via `@puppeteer/browsers install chrome@stable` / `chromedriver@stable` so the pair can never drift apart. Chrome for Testing publishes no linux-arm64 build, so building that image on an Apple Silicon machine needs `--platform linux/amd64`.

## Architecture

Flow: `LinkedinScraper.run(queries)` → one `ThreadPoolExecutor` task per `Query` → inside each task, a loop over `query.options.locations`, each iteration building a **fresh Chrome driver** and delegating to a `Strategy`.

### Strategy selection happens once, at construction

`LinkedinScraper.__init__` picks `AuthenticatedStrategy` if `Config.LI_AT_COOKIE` is set, otherwise `AnonymousStrategy`. `Config.LI_AT_COOKIE` is read from the environment **at import time** (`config.py`), so setting `os.environ` after importing the package has no effect.

`AnonymousStrategy` is explicitly unmaintained (it logs a warning and its selectors are stale). Treat `strategies/authenticated_strategy.py` as the only live scraping path unless asked otherwise.

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
| `on_site_or_remote` | `f_WT` (**only applied when authenticated**) |

Adding a filter means: add the enum member with the code copied from a real LinkedIn search URL, add the mapping in `__build_search_url`, add validation in `QueryFilters.validate`, and document it in the README's filter list.

### Option merging and defaults

`Query.merge_options` fills per-query `None` fields from the global `QueryOptions` passed to `run()`, falling back to hardcoded defaults (`limit=25`, `apply_link=False`, `skip_promoted_jobs=False`, `page_offset=0`). If no global options are given, `run()` synthesises `QueryOptions(locations=['Worldwide'], limit=25)`. Pagination is driven by the `start` query param in steps of `PAGINATION_SIZE` (25, LinkedIn's page size); `page_offset` is a page count, not a job count.

### The results list is virtualized — iterate by job id, never by position

This is the single most important invariant. LinkedIn renders only a handful of job cards at a time and removes the rest from the DOM ("occludable" list), so `document.querySelectorAll('div.job-card-container')` returns a *moving subset* of the page, typically 7–12 of 25. Indexing into that NodeList silently reads the wrong job.

Every item of the list, rendered or not, carries `data-occludable-job-id` (`JOB_ID_ATTRIBUTE`). `AuthenticatedStrategy.__get_job_ids` enumerates those ids once per page, and the jobs loop then addresses each job through `get_job_item_selector(job_id)`. `__load_job_card` scrolls an item into view and polls until its card exists before any field is read. Do not reintroduce positional access.

The list's own scroll container has a runtime-generated obfuscated class name, so it cannot be selected by class; reach it structurally (walk up from the `ul` to the first scrollable ancestor) if you ever need it directly.

### Extraction is JavaScript, not Selenium

Nearly all field extraction is a `driver.execute_script(...)` call with CSS selectors passed as `arguments[n]`. Selenium's own element API is barely used. Waiting is done with hand-rolled poll loops (`__load_job_card`, `__load_job_details`, `__paginate`) that sleep 50 ms and time out, not `WebDriverWait` (one exception: the initial container wait).

Chrome DevTools Protocol is used directly for things Selenium can't do: `Network.enable`, `Page.setBypassCSP`, and `Target.getTargets` / `Target.closeTarget` to capture the off-site apply URL from the tab LinkedIn opens (`__extract_apply_link`).

### Selectors are the fragile surface

Each strategy declares a `Selectors` class at the top of its module. This is where breakage concentrates when LinkedIn ships a UI change, and the git history is mostly selector fixes. "Promoted" detection matches the literal string `'Promoted'` in a list item, so it is locale-dependent (the driver forces `--lang=en-GB` for this reason).

`date_text` reads `…top-card__tertiary-description-container`, whose text is `<place> · <date> · <applicants>` with any segment possibly absent; the date is matched by shape (`/\bago\b|just now/i`) rather than by position, because positional selectors on this node break whenever a segment is missing.

Job "insights" (on-site/remote, contract type, skill-match summary) are `<button>` elements inside `.job-details-fit-level-preferences`, not list items.

LinkedIn no longer exposes required-skill names anywhere in the DOM — only a Premium-gated "N of M skills match" control — so `EventData` has no `skills` field. Do not add one back without checking the live DOM first.

The strategy also defensively dismisses UI that blocks scraping on every pagination round: `__accept_cookies`, `__dismiss_global_alert`, `__close_chat_panel`. `__dismiss_global_alert` clicks `button.artdeco-global-alert__dismiss` by selector, deliberately not by button text, so it works regardless of locale.

### Events

`LinkedinScraper` is a small event emitter (`on` / `once` / `emit` / `remove_listener`). Callback arity is validated at registration: `DATA`, `ERROR`, `METRICS` take exactly one argument; `END` and `INVALID_SESSION` take zero. Only `FunctionType` values pass the `isinstance` check, so plain functions and lambdas work but bound methods and callable objects are rejected.

An exception raised inside a user callback is wrapped as `CallbackException` and re-raised out of `run()`, aborting the scrape. `InvalidCookieException` propagates the same way. Every other exception is swallowed and re-emitted as an `ERROR` event so the run continues. `END` is emitted per query thread, not once per `run()`.

`EventData` is a `NamedTuple`; adding or removing a field means also updating the README's field list and `tests/shared.py`. Note that `x in data` on a `NamedTuple` tests *values*, not field names — never use it to probe for a field's presence.

### Tuning knobs that matter

`slow_mo` (seconds slept between jobs) and `max_workers` exist to avoid HTTP 429. The README recommends `slow_mo >= 0.5` and a single worker in authenticated mode. Increasing default concurrency is a behavioural regression, not an optimisation.

## Gotchas

- Logging goes through `utils/logger.py` to the `li:scraper` namespace; level comes from the `LOG_LEVEL` env var (read at import time). `logger.py` truncates each argument at 1000 chars.
- There is no proxy support. A dead, broken proxy API used to exist on `LinkedinScraper` and in `chrome_driver.py`; it was removed in 6.0.0. Adding real proxy support means wiring `--proxy-server` into `get_default_driver_options`, not restoring the old shape.
- `tmp/` is gitignored scratch space holding downloaded Chrome/chromedriver builds — not part of the package.
- Chrome/chromedriver version compatibility is the most common source of local-only failures, and Selenium Manager will *not* rescue a mismatched driver already on `PATH` — it warns and then fails with `SessionNotCreatedException`. `chrome_executable_path` (chromedriver) and `chrome_binary_location` (Chrome/Chromium binary) let a caller pin a matched pair; running `tests/run_tests.sh` in the container avoids the problem entirely.
