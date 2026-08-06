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
- **A pair copied out of an everyday browser is refused**, even though both halves are readable in the developer tools panel. Same account, same machine, same Chrome build: the pair the login command prints worked ten times over, the one read from a normal signed-in browser was refused four times, including with `bscookie`, `liap` and `JSESSIONID` added. Truncation, the quotes in `bcookie`'s value, account-level causes and Device Bound Session Credentials were all ruled out; the mechanism is unknown. So the login command is the only supported source, and the README must not tell anyone to use devtools for the pair. `li_at` on its own is unaffected and still copyable.
- An injected pair **must carry an expiry** (`REMEMBER_COOKIE_MAX_AGE`): `add_cookie` without one creates a session cookie that Chrome discards on exit, which left a profile holding a session and nothing able to renew it. `bcookie` masked the bug by surviving anyway — LinkedIn re-sends it with an expiry of its own.

### Sessions: the profile wins

`utils/session.py` owns the cookies a session is made of. `user_data_dir` gives the browser a profile that survives across runs, and a session already in that jar takes precedence over anything supplied — which is what lets a profile be seeded once and then run with an empty environment. Chrome locks a profile directory, so `max_workers` is forced to 1 when one is set.

Recovery from a retired session needs **no UI automation at all**: with `li_rm` present, a request to an authenticated route has a fresh session issued silently, so `__recover_session` just navigates to `FEED_URL` and waits. Reproduce the retired state on demand with `driver.delete_cookie('li_at')` on the profile, keeping `li_rm`.

`interactive_login` is the only path that opens a visible browser, it requires `user_data_dir`, and it is off by default because it waits up to 10 minutes for a human — a default that would hang CI. `login.ensure_session` spends one short lived headless browser deciding whether a sign in is needed at all (`has_credentials`: does the profile hold `li_at` or `li_rm`?), which is cheaper than opening a window somebody has to close. It runs in `run()` before any worker starts, because Chrome locks the profile.

Three traps here, each hit once:

- **Never read the cookie jar straight after a navigation.** `page_load_strategy` is `'none'`, so `driver.get` returns before the response carrying the cookie is processed. `__wait_for_session` polls for up to `SESSION_WAIT_TIMEOUT`; checking immediately reported an empty jar on a profile that had a session a second later.
- **`Selectors.appShell` does not match `/feed/`**, whose class names are obfuscated hashes; it matches the jobs pages only. `login.py` waits to be past the sign in pages (`Selectors.signInForm` plus `SIGN_IN_PATHS`) rather than for the shell, which is why it no longer hangs on a good session.
- **A supplied pair must not overwrite a profile's own.** `li_rm` is bound to the `bcookie` it was issued with, so replacing half of a profile's pair with half of somebody else's breaks both. `__authenticate` injects only when the jar holds no `li_rm`.

`__open_results` answers a refusal by emptying the jar of its session and authenticating once more, then retrying the page. This is what makes a fresh credential usable against a profile holding a retired one: the jar is consulted first, so without it a stale profile cookie would keep winning and the run would die with the caller's good cookie never tried. Both of LinkedIn's refusals are treated the same, since the jar proves nothing either way — cookie cleared, or cookie kept and the logged out page served. If the retry gets a session that still renders no results the location is skipped (throttling looks exactly like that); if it gets no session at all, `InvalidCookieException` aborts the run.

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

Chrome DevTools Protocol is used directly for things Selenium can't do: `Network.setUserAgentOverride` for the headless masking, and `Target.getTargets` / `Target.closeTarget` to capture the off-site apply URL from the tab LinkedIn opens (`__extract_apply_link`).

`__paginate` waits as long as the initial container wait, retries once after `PAGINATION_RETRY_DELAY`, and reports `__describe_page` when it gives up. Pagination is intermittent — identical configurations have both failed and succeeded — so that dump (ready state, container and guest markers, item count, title, URL, leading visible text) is the way into the next failure.

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

`slow_mo` (seconds slept between jobs) and `max_workers` exist to avoid HTTP 429. The README recommends `slow_mo >= 0.5` and a single worker in authenticated mode. Increasing default concurrency is a behavioural regression, not an optimisation.

## Gotchas

- Logging goes through `utils/logger.py` to the `li:scraper` namespace; level comes from the `LOG_LEVEL` env var (read at import time). `logger.py` truncates each argument at 1000 chars.
- `tests/manual/validate_fields.py` needs `PYTHONPATH` set to the directory holding the package (`/app` in the container). Running a file by path puts *its own* directory on `sys.path`, not the working directory, so without it the import of `linkedin_jobs_scraper` fails.
- There is no proxy support. A dead, broken proxy API used to exist on `LinkedinScraper` and in `chrome_driver.py`; it was removed in 6.0.0. Adding real proxy support means wiring `--proxy-server` into `get_default_driver_options`, not restoring the old shape.
- `tmp/` is gitignored scratch space holding downloaded Chrome/chromedriver builds — not part of the package.
- Chrome/chromedriver version compatibility is the most common source of local-only failures, and Selenium Manager will *not* rescue a mismatched driver already on `PATH` — it warns and then fails with `SessionNotCreatedException`. `chrome_executable_path` (chromedriver) and `chrome_binary_location` (Chrome/Chromium binary) let a caller pin a matched pair; running `tests/run_tests.sh` in the container avoids the problem entirely.
