# The Selenium surface to port

Answers #142 for map #139: what moving this package off Selenium to a CDP/Playwright-style API
(Patchright is the lead candidate) would cost, file by file, and which parts have no clean
counterpart. Surveyed at master `68aa361`. Nothing here was run against LinkedIn.

Sources: this repository; the Playwright Python API reference
(<https://playwright.dev/python/docs/api/class-page>, `class-browsercontext`, `class-browsertype`,
`class-cdpsession`, `class-keyboard`, `class-playwright` for errors); the Patchright Python README
(<https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python>).

## Verdict

About **L overall: 3 L, 6 M, the rest S**, plus a rewrite of the unit-test fakes. Most call
sites go through three wrappers (`run_script`, `run_async_script`, `run_cdp` in
`utils/page_script.py`), so the call count is small; the cost is in semantics, not in volume. The
four places that do not port line for line:

1. **Launch and headless masking** (`utils/chrome_driver.py`). Selenium Manager, the chromedriver
   service, `ChromeOptions` and the throwaway browser that learns the User-Agent all disappear.
   Patchright's README says to use `launch_persistent_context(channel="chrome", headless=False,
   no_viewport=True)` and "do NOT add custom browser headers or user_agent", which conflicts with
   the current `--user-agent` + `Network.setUserAgentOverride` masking. Whether to keep it is a
   detectability question for the evidence ladder, not a porting one.
2. **`page_load_strategy='none'` and "None while the document is replaced"**. `driver.get` returns
   at once and `execute_script` answers `None` during a navigation; the strategy is written around
   both (comments at `authenticated_strategy.py` lines ~500, ~1072, ~1158). The nearest Playwright
   form is `page.goto(url, wait_until="commit")`, and `page.evaluate` raises ("Execution context
   was destroyed") instead of returning `None`. Every polling loop has to be rechecked.
3. **Cookies**. Selenium's `get_cookie` reads the jar of the document on screen, which AGENTS.md
   relies on ("the cookie jar is that of the document on screen"). Playwright's
   `context.cookies(urls)` reads the context's jar regardless of the page, and `add_cookies` does
   not need the page to be on the domain first. Session-loss judgement (`_is_session_lost`) needs
   re-proving.
4. **The `tests/browser` harness** subclasses `webdriver.Chrome` to append
   `--host-resolver-rules` to every launch. Playwright has no class to subclass; the seam has to
   become a launch function in `chrome_driver.py` that the harness monkeypatches (the Chrome flags
   themselves still pass through `args=`).

Clean mappings: `execute_async_script` callback scripts become `async` functions passed to
`page.evaluate`; `execute_cdp_cmd` becomes `context.new_cdp_session(page).send(...)`;
`window_handles`/`switch_to`/`Target.getTargets`/`Target.closeTarget` become `context.pages`,
the `page` event and `page.close()`; `ActionChains`/`Keys` become `page.mouse`/`page.keyboard`
and locators; `WebDriverWait` becomes `page.wait_for_function`. The error split
(`WebDriverException` vs urllib3 `HTTPError`) collapses into Playwright's `Error`/`TimeoutError`
hierarchy, which removes a known failure class.

Script dialect: every page script uses Selenium's `return` + `arguments[n]` form (27
`arguments[` uses in the package). Playwright's `evaluate` takes one function expression and a
single argument, so each script is rewritten mechanically. Patchright runs `evaluate` in an
isolated world by default (`isolated_context=True`); the scripts only read the DOM and click, which
the isolated world shares, but each needs checking. Patchright also disables the Console API.

Sync or async: the scraper runs queries on a `ThreadPoolExecutor` (`max_workers`, default 1).
Playwright's sync API is per thread, so each worker would start its own `sync_playwright()`; that
fits the current one-browser-per-worker shape.

## File by file

| File | Selenium touchpoints | Size | Notes |
|---|---|---|---|
| `linkedin_jobs_scraper/utils/chrome_driver.py` (430) | `webdriver.Chrome`, `ChromeService`, `ChromeOptions` (20+ args, `excludeSwitches`, `useAutomationExtension`, prefs), `SeleniumManager().binary_paths`, `page_load_strategy='none'`, `set_page_load_timeout`, UA probe browser, `execute_async_script` for `getHighEntropyValues`, `execute_cdp_cmd('Network.setUserAgentOverride')`, `quit` swallowing urllib/HTTP errors | **L** | Rewrite. Driver resolution has no counterpart (browser comes from `channel="chrome"` or `patchright install chrome`). Patchright already adds `--disable-blink-features=AutomationControlled` and drops `--enable-automation`. Download-blocking prefs have no options API: persistent profile prefs or `accept_downloads=False`. Masking policy needs a decision (see Verdict 1). |
| `linkedin_jobs_scraper/strategies/authenticated_strategy.py` (2129) | 19 `run_script`, 4 `driver.get`, `delete_cookie`, `current_url`, `window_handles`, `switch_to.window`, `Target.getTargets`/`closeTarget` via CDP, `WebDriverException`, `BROWSER_ERRORS` | **L** | Call sites are few but the navigation and polling model rests on `page_load_strategy='none'` (Verdict 2). Apply-link capture becomes `context.expect_page()` / `page` event, reading the popup URL before it redirects off site. |
| `linkedin_jobs_scraper/linkedin_scraper.py` (622) | public `chrome_options: Options` with `isinstance` check, `chrome_executable_path`, `build_driver`/`quit_driver`, `driver.get` | **M** | Public API break: both parameters are replaced (allowed without shim per #139). Docstrings. |
| `linkedin_jobs_scraper/utils/location_picker.py` (234) | `find_element(By.CSS_SELECTOR)`, `ActionChains` move/click/send_keys, `Keys.BACKSPACE`, 3 scripts | **M** | `page.locator(...).click()`, `page.keyboard.press/type`. Human-like input must stay human-like (`slow_mo`, typing delay). |
| `linkedin_jobs_scraper/login.py` (340) | headed `build_driver`, `window_handles` to see the user close the window, `current_url`, `get_cookie`, `driver.get` | **M** | Closed-window detection becomes `page.is_closed()` / `close` event. |
| `linkedin_jobs_scraper/utils/session.py` (170) | `get_cookie`, `add_cookie`, hostname script | **M** | Cookie-jar semantics change (Verdict 3). |
| `linkedin_jobs_scraper/utils/page_script.py` (164) | `execute_script`, `execute_async_script`, `execute_cdp_cmd` wrappers | **S** | Three wrappers; the `as_*`/`read_*` narrowing stays. |
| `linkedin_jobs_scraper/utils/browser_errors.py` | `WebDriverException`, urllib3 `HTTPError` | **S** | Becomes Playwright `Error`; the split disappears. |
| `linkedin_jobs_scraper/utils/session_source.py` (206) | reads `--user-data-dir` out of `Options.arguments` | **S** | Profile becomes the `user_data_dir` argument of `launch_persistent_context`. |
| `linkedin_jobs_scraper/cli/args.py`, `cli/mapping.py`, `cli/main.py` | `--chrome-executable-path` flag | **S** | Rename or drop the flag. |
| `linkedin_jobs_scraper/exceptions/exceptions.py` | `ChromedriverResolutionException` | **S** | Goes away or becomes a browser-install error. |
| `tests/unit/*` (fakes in `test_interrupts`, `test_job_events`, `test_session`, `test_session_source`, `test_search_paths`, `test_browser_masking`, `test_browser_errors`, `test_page_script`, `test_cli_mapping`, `test_pacing`, `test_cli_login`) | hand-written `FakeDriver` classes mimicking `execute_script`/`execute_cdp_cmd`/cookies; Selenium exception types; `Options()` | **M–L** | Fakes are keyed on WebDriver method names and must mirror the new Page/Context surface. `test_chrome_driver_resolution.py` (244) is deleted; `test_browser_errors.py` (384) rewritten. |
| `tests/browser/*` (716) | `BlockedChrome(webdriver.Chrome)`, `SE_OFFLINE`, `WebDriverWait`, `TimeoutException`, `navigator.webdriver` check | **M** | Seam moves to a launch function (Verdict 4). Fake LinkedIn server and pages unchanged. |
| `tests/manual/*` | `remote_probe.py` standalone Selenium; `network_headers_probe.py` uses Selenium BiDi internals | **S–M** | Probes can stay on Selenium as historical tools or be ported; Playwright's `page.on("request")`/`route` replaces the BiDi internals more simply. |
| `tests/test_programmatic.py`, `tests/test_cli.py` (e2e) | logger names only | **S** | |
| `README.md` | Selenium Manager, chromedriver, `chrome_options`, `chrome_executable_path`, logger names | **M** | Install section and options reference rewritten; migration guide. |
| `pyproject.toml` | `selenium>=4.51.0`, `urllib3>=2.6.3` | **S** | Replace with `patchright`. |
| `package.json` | `test:browser:driver` calls `resolve_chromedriver_paths` | **S** | Becomes `patchright install chrome`. |
| `.github/workflows/ci.yml` | browser job runs `test:browser:driver` | **S** | Browser install step. |
| `CHANGELOG.md` | | **S** | Major-version entry. |

## Total

Three L (`chrome_driver.py`, `authenticated_strategy.py`, the unit-test fakes taken together),
six M (`linkedin_scraper.py`, `location_picker.py`, `login.py`, `session.py`, `tests/browser`,
`README.md`), the rest S. The code change itself is mechanical outside the four
Verdict items; those four need live proof under the AGENTS.md rules, and item 1 is gated by the
detectability comparison in #139, not by porting effort.
