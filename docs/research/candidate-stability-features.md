# Stability and features of the candidate stacks (issue #143)

Survey date: 2026-11-27. Reading only: nothing was run against LinkedIn or any site. Candidates and versions come from the shortlist (`origin/research/stealth-stack-shortlist:docs/research/stealth-stack-shortlist.md`): Patchright 1.64.4, SeleniumBase UC/CDP Mode 4.59.1, Pydoll 3.0.1, Zendriver 0.18.0. Settled: installed Google Chrome (channel `chrome`), keep `--use-mock-keychain --password-store=basic`.

Issue-tracker evidence below is a sample of titles and bodies read on the survey date, not a full audit. GitHub search hit its rate limit part way, so Zendriver was surveyed from its last 100 issues instead of keyword search.

## What the package relies on today

| Reliance | Where |
|---|---|
| Selenium >= 4.51 plus urllib3 | `pyproject.toml` |
| `page_load_strategy = 'none'`: navigation returns at once, code waits for positive signs | `linkedin_jobs_scraper/utils/chrome_driver.py` (`get_default_driver_options`), AGENTS.md "Absence proves nothing" |
| `driver.set_page_load_timeout(timeout)` | `chrome_driver.py` (`build_driver`) |
| chromedriver from Selenium Manager matched to the Chrome binary, or an explicit path | `chrome_driver.py` (`_build_chrome_service`), README lines 58-66 |
| `--headless=new` plus a masked User-Agent: a throwaway browser learns the UA, it is passed as `--user-agent` so every target inherits it, and `Network.setUserAgentOverride` with client hints covers the main target | `chrome_driver.py` (`resolve_masked_user_agent`, `mask_headless_user_agent`) |
| `--user-data-dir` persistent profile, `--lang=en-GB`, window size, `excludeSwitches: enable-automation`, `--disable-blink-features=AutomationControlled`, prefs that block downloads | `chrome_driver.py` |
| `execute_async_script` for page scripts that return raw strings | `linkedin_jobs_scraper/utils/page_script.py` |
| CDP calls via `execute_cdp_cmd`: `Network.setUserAgentOverride`, `Target.getTargets`, `Target.closeTarget` | `page_script.py` (`run_cdp`), `chrome_driver.py`, `strategies/authenticated_strategy.py` (two sites) |
| Several tabs: apply links open a new tab, handled via `window_handles`, `switch_to.window`, and closed via `Target.closeTarget` | `authenticated_strategy.py` (around the `window_handles` uses) |
| Cookies of the document on screen: `driver.get_cookie(name)` for `li_at` and the remember-me cookie | `linkedin_jobs_scraper/utils/session.py` (`get_cookie`), `login.py` |
| Two error families: `WebDriverException` for Chrome failures, urllib3 `HTTPError` when chromedriver has exited; `quit_driver` also swallows `OSError`/`HTTPException` | `linkedin_jobs_scraper/utils/browser_errors.py`, `chrome_driver.py` (`quit_driver`) |
| No proxy support and no network interception today | grep of `linkedin_jobs_scraper/` (no proxy or Fetch usage) |

## Failure classes from this repo's history

- #14 `KeyError: 'goog:chromeOptions'`: reading `debuggerAddress` from Selenium capabilities, which a driver/Selenium mismatch did not return. https://github.com/spinlud/py-linkedin-jobs-scraper/issues/14
- #77 How the Dockerfile's chromedriver is meant to be used: manual driver setup in Docker. https://github.com/spinlud/py-linkedin-jobs-scraper/issues/77
- #90 `JavascriptException` on Chrome 127. The root cause was a page change (a selector returned undefined), not driver skew; it shows up as a WebDriver error all the same. https://github.com/spinlud/py-linkedin-jobs-scraper/issues/90
- #40 "Timed out receiving message from renderer" on `driver.get` (Chrome 105): chromedriver waiting for a load that never completed. https://github.com/spinlud/py-linkedin-jobs-scraper/issues/40
- #48 "session deleted because of page crash" in a 500 MB Docker container: renderer out of memory. https://github.com/spinlud/py-linkedin-jobs-scraper/issues/48
- #18 Proxy authentication: Chrome has no flag for proxy credentials; the workaround was an extension, which does not load in headless. https://github.com/spinlud/py-linkedin-jobs-scraper/issues/18

## Matrix

Legend: removes / keeps / adds for failure classes; has / lacks for features. Cites are numbered in Sources.

| | Selenium (today) | Patchright 1.64.4 | SeleniumBase UC/CDP 4.59.1 | Pydoll 3.0.1 | Zendriver 0.18.0 |
|---|---|---|---|---|---|
| Driver resolution, version skew (#14, #77, #90) | keeps, mitigated: Selenium Manager fetches a matching chromedriver [code] | removes chromedriver; adds a bundled Node driver pinned per release, and Chrome-channel install on Linux arm64 fails [P3] | keeps: patched `uc_driver` must match Chrome; Chrome-version breakage seen [S2] | removes driver; adds CDP schema drift risk (hand-written types) | removes driver; adds CDP schema drift: `KeyError` on Chrome 146 in network and cookies [Z2, Z3] |
| Renderer timeouts (#40) | keeps, mitigated by `page_load_strategy='none'` [code] | removes chromedriver timeout; adds own hangs: `load` never fires behind auth proxy (fixed) [P4], Frame loop at 100% CPU (fixed) [P5] | keeps in UC Mode; new 4.58+ regression: `driver.get` on 4xx closes the only tab, next command fails after ~60 s (open) [S3] | adds: commands on a crashed tab waited for the full timeout (fixed 2026-10) [D2]; frozen browser reported alive (fixed) [D3] | adds: `Network.enable` hang in `Tab.get` (fixed) [Z4] |
| Page crash, memory (#48) | keeps (Chrome itself) | keeps (Chrome itself); "Target crashed" now raised [P6] | keeps; orphaned Chrome locks `user_data_dir` after crash (fixed) [S4] | keeps; crashed browser left process and temp profile behind (fixed) [D4] | keeps |
| Proxy authentication (#18) | lacks (extension only, not headless; Chrome 142 dropped `--load-extension` [S5]) | has: `proxy={server, username, password}` at launch, handled over CDP [P1] | has via extension loaded over CDP pipe on Chrome 142+ [S6] | has but buggy: auth proxy navigation timeout, open since 2026-01 [D1] | has: `Browser.create_context()` with auth proxy (added 2026-09) [Z5] |
| urllib3 vs WebDriver error split | keeps [browser_errors.py] | removes; one `playwright.Error`/`TimeoutError` family [P1] | keeps (Selenium underneath) plus CDP-mode errors: a third family | removes; own exception tree [D0] | removes; own exceptions plus asyncio/websocket errors |
| Docker setup | keeps: Chrome + Selenium Manager; no official image here | official Playwright base images exist, but Chrome channel needs `patchright install chrome` (no Linux arm64) [P3] | headless Linux expects Xvfb for UC Mode [shortlist]; arm64 Linux drivers added 2026-11 [S7] | user-provided Chrome only | official Docker guide in README [Z1]; open deploy questions [Z6, Z7] |
| Network interception | lacks (only via CDP by hand) | has: `route`, `on("request"/"response")` [P1] | has in CDP Mode | has: Fetch-based interception [D0] | has: CDP Fetch/Network handlers [Z1] |
| Waiting primitives | has: `WebDriverWait` + own positive-sign polling | has: auto-waiting locators, `wait_for_function`, `wait_for_url` [P1] | has: rich `wait_for_*` helpers | has: `find(..., timeout=)`, `wait_until` [D0] | has: `find`/`select` with timeout, `wait_for_ready_state` [Z8] |
| Multiple tabs / targets | has: window handles + raw `Target.*` | has: `context.on("page")`, `page.close()`; popups first-class [P1] | has (Selenium handles; reuse of a profile showed extra handles, fixed) [S8] | has: tabs as objects, new-tab events [D0] | has: tabs as objects [Z1] |
| Persistent profile | has: `--user-data-dir` | has: `launch_persistent_context(user_data_dir, channel="chrome")` [P2]; hang on 3rd reuse of same dir (Node, fixed) [P7] | has: `user_data_dir=` | has via `--user-data-dir` argument (docs unclear) [shortlist] | has: `user_data_dir` [Z1] |
| Headless | has: `--headless=new` + own UA masking | has, but stealth claim covers headed only [P2]; UA masking still needed | has: "Super Headless Stealth" in CDP Mode, very new (2026-11-25) [S9] | has; no headless-marker handling documented [shortlist] | has: headless UA and client-hint fixes for all targets (2026-10) [Z9] |
| Cookies of the document on screen | has: `driver.get_cookie` | changes: `context.cookies(urls)` returns the jar, not the document's view [P1] | has (Selenium) | changes: CDP `Network`/`Storage` cookies | changes: `browser.cookies` (crashed on Chrome 146, fixed) [Z3] |
| Async page script returning a string | has: `execute_async_script` | has: `page.evaluate` awaits promises; Patchright runs in an isolated world by default, so page globals need `isolated_context=False` [P2] | has (Selenium) | has: `execute_script` / Runtime evaluate [D0] | has: `tab.evaluate(await_promise=True)` [Z1] |
| Sync API | has | has [P1] | has | has, generated from async [shortlist] | lacks: async only [shortlist] |
| Tracks new Chrome | Selenium Manager, monthly Selenium releases | follows Playwright monthly; Python port lags Node (last Python tag v1.62.0 on GitHub, PyPI at 1.64.4) [P8] | releases every few days [S1] | ~monthly [D5] | ~monthly; Chrome 146 breakage fixed same month [Z2] |

## Per-candidate notes

### Selenium (current)
Driver skew is mostly solved by Selenium Manager (`_build_chrome_service`). What stays: the two error families, chromedriver's own timeouts, and no proxy auth now that Chrome 142 dropped `--load-extension` [S5]. Lowest migration cost: zero. Maintenance risk low (Selenium project).

### Patchright
Removes chromedriver and the error split, adds proxy auth, interception, auto-waiting and first-class popups. Gaps for this package: page scripts run in an isolated world by default, and the console is disabled [P2]; cookies come from the context jar, which changes the "document on screen" rule in AGENTS.md; `patchright install chrome` fails on Linux arm64 (open) [P3, P10]. Recent bugs are real but fixed quickly (auth-proxy hang [P4], CPU loop [P5], persistent-profile reuse hang [P7]). Maintenance risk: high bus factor on the Python port. Vinyzu has 88 of ~90 commits across 5 contributors [P9]; the core benefits from upstream Playwright (44 contributors, mostly Microsoft). Breaking changes track Playwright, which is stable.

### SeleniumBase UC/CDP Mode
Keeps Selenium, so keeps the error split and chromedriver (now a patched one), and adds a third mode with reconnect semantics. Proxy auth works through an extension it loads over CDP [S6]. A current open regression closes the tab on 4xx pages [S3]. Headless stealth landed two days before this survey [S9]. Maintenance risk: one maintainer writes nearly everything (mdmintz 10,508 commits; next contributor 14) [S1]; very fast cadence (12 releases in ~5 weeks) means frequent behaviour changes.

### Pydoll
Removes the driver and the error split; adds a sync API, interception and tabs as objects. Gap: authenticated proxy navigation hangs, open since 2026-01 [D1]. Several crash/freeze handling bugs were fixed only in 2026-10 [D2, D3, D4]. 3.0 broke the API in 2026-09. Maintenance risk: one main author (thalissonvs 1,271 commits; next human 36) [D5].

### Zendriver
Removes the driver and the error split; most explicit headless work (UA and client hints for all targets, screen size [Z9]), which overlaps with this package's own masking. Auth proxy since 2026-09 [Z5]. Gaps: async only, so the package needs a sync wrapper; generated CDP bindings broke on a Chrome 146 rename [Z2, Z3]; extensions broken on Chrome 139+ (open) [Z10]. Maintenance risk: most spread of the four (stephanlensky 225, then 46 and 27; 37 contributors), but 58 open issues and 0.x versioning.

## Is anything the package relies on missing?

- Patchright: no `execute_cdp_cmd` equivalent on the page by default, but `context.new_cdp_session(page)` exists [P1]; isolated-world evaluation and context-wide cookies need adapting. `page_load_strategy='none'` maps to `goto(wait_until="commit")`.
- SeleniumBase: nothing missing in UC Mode; `driver.get` may reconnect and behave differently [shortlist].
- Pydoll and Zendriver: nothing structurally missing; every reliance maps to CDP, but each needs re-implementing (cookies, targets, UA override), and Zendriver needs an async-to-sync layer.

## Verdicts

- Selenium: keeps every historical class except driver skew, which Selenium Manager already handles; no proxy auth. Baseline.
- Patchright: removes the most classes (driver, error split, proxy auth) with mature waiting and tab APIs; costs are the isolated-world and cookie semantics, Linux arm64 Chrome, and a one-person Python port.
- SeleniumBase: smallest port but removes nothing structural (keeps chromedriver and the error split) and adds reconnect semantics and fast churn from one maintainer.
- Pydoll: removes driver and error split with a sync API, but authenticated proxy is broken and crash handling only recently fixed.
- Zendriver: removes driver and error split and has the best headless work, but async only and exposed to CDP schema drift on new Chrome releases.

## Uncertainties

- No candidate was run. All crash and hang evidence comes from issue trackers, which over-represent users of the busiest projects (SeleniumBase).
- Whether Patchright's isolated-world evaluation can read the page state the current page scripts read; needs a rung-1 check.
- Pydoll's persistent-profile handling is not documented.

## Sources

Repo files (worktree): `linkedin_jobs_scraper/utils/chrome_driver.py`, `linkedin_jobs_scraper/utils/browser_errors.py`, `linkedin_jobs_scraper/utils/page_script.py`, `linkedin_jobs_scraper/utils/session.py`, `linkedin_jobs_scraper/strategies/authenticated_strategy.py`, `linkedin_jobs_scraper/login.py`, `pyproject.toml`, `README.md`, `AGENTS.md`. Shortlist: `origin/research/stealth-stack-shortlist:docs/research/stealth-stack-shortlist.md`.

Repo issues: https://github.com/spinlud/py-linkedin-jobs-scraper/issues/14, /18, /40, /48, /77, /90

Patchright
- [P1] https://playwright.dev/python/docs/api/class-browsertype (proxy, persistent context), https://playwright.dev/python/docs/network
- [P2] https://github.com/Kaliiiiiiiiii-Vinyzu/patchright (README: patches, isolated contexts, console off, best practice)
- [P3] https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python/issues/121
- [P4] https://github.com/Kaliiiiiiiiii-Vinyzu/patchright/issues/259
- [P5] https://github.com/Kaliiiiiiiiii-Vinyzu/patchright/issues/246
- [P6] https://github.com/Kaliiiiiiiiii-Vinyzu/patchright/issues/146
- [P7] https://github.com/Kaliiiiiiiiii-Vinyzu/patchright/issues/201
- [P8] https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python/releases, https://pypi.org/pypi/patchright/json
- [P9] https://api.github.com/repos/Kaliiiiiiiiii-Vinyzu/patchright-python/contributors, https://api.github.com/repos/Kaliiiiiiiiii-Vinyzu/patchright/contributors
- [P10] https://github.com/Kaliiiiiiiiii-Vinyzu/patchright/issues/211

SeleniumBase
- [S1] https://github.com/seleniumbase/SeleniumBase/releases, https://api.github.com/repos/seleniumbase/SeleniumBase/contributors
- [S2] https://github.com/seleniumbase/SeleniumBase/issues/4393
- [S3] https://github.com/seleniumbase/SeleniumBase/issues/4587
- [S4] https://github.com/seleniumbase/SeleniumBase/issues/4349
- [S5] https://github.com/seleniumbase/SeleniumBase/issues/4053
- [S6] https://github.com/seleniumbase/SeleniumBase/issues/4529
- [S7] https://github.com/seleniumbase/SeleniumBase/issues/4546
- [S8] https://github.com/seleniumbase/SeleniumBase/issues/4336
- [S9] https://github.com/seleniumbase/SeleniumBase/issues/4574, https://github.com/seleniumbase/SeleniumBase/issues/4585

Pydoll
- [D0] https://github.com/autoscrape-labs/pydoll (README)
- [D1] https://github.com/autoscrape-labs/pydoll/issues/353
- [D2] https://github.com/autoscrape-labs/pydoll/issues/469
- [D3] https://github.com/autoscrape-labs/pydoll/issues/471
- [D4] https://github.com/autoscrape-labs/pydoll/issues/473
- [D5] https://github.com/autoscrape-labs/pydoll/releases, https://api.github.com/repos/autoscrape-labs/pydoll/contributors

Zendriver
- [Z1] https://github.com/cdpdriver/zendriver (README, Docker section)
- [Z2] https://github.com/cdpdriver/zendriver/issues/249, https://github.com/cdpdriver/zendriver/pull/250
- [Z3] https://github.com/cdpdriver/zendriver/issues/244
- [Z4] https://github.com/cdpdriver/zendriver/issues/226
- [Z5] https://github.com/cdpdriver/zendriver/pull/284
- [Z6] https://github.com/cdpdriver/zendriver/issues/204
- [Z7] https://github.com/cdpdriver/zendriver/issues/255
- [Z8] https://github.com/cdpdriver/zendriver/pull/291
- [Z9] https://github.com/cdpdriver/zendriver/pull/293, /295, /296, /297
- [Z10] https://github.com/cdpdriver/zendriver/issues/229
- Contributors and releases: https://api.github.com/repos/cdpdriver/zendriver/contributors, https://github.com/cdpdriver/zendriver/releases
