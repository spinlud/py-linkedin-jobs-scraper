# Stealth automation stacks: shortlist (issue #140, map #139)

Survey date: 2026-11-27. Nothing was run against LinkedIn or any third-party site. All facts come from the projects' own repos, READMEs and PyPI release history, read on the survey date. The leak lists come from the maintainers. No independent benchmark compares these stacks on the same pages. Rung 1 of the map's evidence ladder (offline fingerprint pages) has to produce that comparison.

Criteria from the ticket: Python, latest release no older than 6 months (on or after 2026-05-27), widely used, drives Chrome/Chromium with a persistent profile.

## Field surveyed

| Stack | PyPI latest (date) | GitHub stars | Engine | Verdict |
|---|---|---|---|---|
| Patchright | 1.64.4 (2026-11-02) | 1.6k (Python repo) | Patched Playwright | **Always on the list** |
| SeleniumBase (UC / CDP Mode) | 4.59.1 (2026-11-25) | 13.3k | Selenium + CDP (MyCDP) | **Kept** |
| Pydoll | 3.0.1 (2026-11-08) | 7.2k | Raw CDP | **Kept** |
| Zendriver | 0.18.0 (2026-11-21) | 1.5k | Raw CDP (nodriver fork) | **Kept** |
| nodriver | 0.50.99 (2026-10-26) | 5.0k | Raw CDP | Rejected: Zendriver covers it |
| undetected-chromedriver | 3.5.5 (2024-02-17) | 12.9k | Patched chromedriver | Rejected: unmaintained |
| Camoufox | 0.5.9 (2026-11-01) | 13.7k | Patched Firefox | Rejected: not Chrome |
| DrissionPage | 4.1.1.4 (2026-05-27) | 12.6k | CDP | Rejected: on the 6-month edge, stealth not documented |
| Botasaurus | 4.0.97 (2026-01-06) | 5.9k | CDP | Rejected: no release in 6 months |
| rebrowser-playwright | 1.64.102 (2026-11-02) | 107 | Patched Playwright | Rejected: not widely used, same idea as Patchright |
| playwright-stealth | 2.0.3 (2026-04-04) | 273 | JS evasion scripts on Playwright | Rejected: stale, does not fix protocol leaks |

Sources: `https://pypi.org/pypi/<name>/json` and `gh api repos/<owner>/<repo>`.

## Patchright (on the list in any case)

- Source: https://github.com/Kaliiiiiiiiii-Vinyzu/patchright (README "Patches"), https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python
- API: sync (`patchright.sync_api`) and async (`patchright.async_api`). It is a drop-in replacement for Playwright.
- Persistent profile: `chromium.launch_persistent_context(user_data_dir=..., channel="chrome", headless=False, no_viewport=True)`. The README calls this setup its "best practice" for staying undetected.
- Patches:
  - It never calls `Runtime.enable` and runs JS in isolated ExecutionContexts.
  - `Console.enable` is off, so the console API does not work.
  - Launch flags: it adds `--disable-blink-features=AutomationControlled` and removes `--enable-automation` and `--disable-component-update`.
  - It fixes several general Playwright leaks and works inside closed shadow roots.
- Leaks the maintainers admit:
  - Timing attacks can detect init scripts, because they are injected through routes. The maintainers say no antibot checks for this today.
  - There is no console.
  - The claim of being undetectable covers only headed Chrome with no fingerprint injection.
- Evidence: the maintainers' own list says it passes Brotector (with CDP-Patches), Cloudflare, Fingerprint.com, CreepJS and others. It is self-reported.

## Kept

### SeleniumBase (UC Mode / CDP Mode)

- Reason: the most widely used option (13.3k stars, a release every few days). It is the shortest path from the current Selenium code, because UC Mode is still a Selenium `driver`.
- Source: https://github.com/seleniumbase/SeleniumBase/blob/master/help_docs/uc_mode.md, https://github.com/seleniumbase/SeleniumBase/blob/master/examples/cdp_mode/ReadMe.md
- API: sync (`SB`, `Driver`). Pure CDP Mode also has an async API (`cdp_driver.start_async()`).
- Persistent profile: the `user_data_dir=` option.
- Patches:
  - UC Mode runs a modified chromedriver (`uc_driver`) and disconnects WebDriver from Chrome at key moments (`uc_open_with_reconnect`).
  - CDP Mode drives the page over CDP while WebDriver is disconnected.
- Leaks the maintainers admit:
  - "Reconnecting allows anti-bot systems to detect you". WebDriver-only methods force a reconnect.
  - `driver.get` behaves differently from plain Selenium: it may reconnect.
  - Some sites need `incognito=True`, which conflicts with a persistent profile.
  - Headless Linux needs its Xvfb virtual display (the `SB` manager).
- Evidence: the docs report passing BrowserScan, Sannysoft and Pixelscan, and point to CI runs in `mdmintz/undetected-testing`. It is self-reported.

### Pydoll

- Reason: widely used (7.2k stars, 3.0.1 in November 2026). It is the only CDP-native stack with a first-class sync and async API, and it has a Playwright-compatible layer.
- Source: https://github.com/autoscrape-labs/pydoll README ("Staying undetected")
- API: async (`from pydoll import Chrome`) and sync (`from pydoll.sync import Chrome`). The sync API is generated from the async one.
- Persistent profile: Chrome's `--user-data-dir` argument through browser options. Its docs do not confirm this yet. Check it before rung 1.
- Patches:
  - It has no WebDriver at all. The README says `navigator.webdriver`, `--enable-automation` and `Runtime.enable` "are never there to begin with".
  - Optional fingerprint injection stays consistent across workers and survives `toString` checks.
  - Mouse, typing and scrolling are humanized.
- Leaks and risks:
  - Fingerprint injection is itself a lie that detectors look for. This package already avoids spoofing.
  - The README says nothing about headless markers, so `--headless=new` still needs the package's current User-Agent masking.
  - Version 3 just changed the API with breaking changes.
- Evidence: self-reported only (it says CreepJS's lie detection does not flag its overrides, and that it passes Turnstile "depending on your browser and IP reputation").

### Zendriver

- Reason: the actively maintained, open-contribution fork of nodriver, which is the official successor of undetected-chromedriver. It has first-class Docker support.
- Source: https://github.com/cdpdriver/zendriver README
- API: async only. The package would need its own sync wrapper.
- Persistent profile: `user_data_dir` in `start(...)` / `Config`, inherited from nodriver. The nodriver README says a profile passed this way is not cleaned up.
- Patches: CDP only, with no Selenium or WebDriver. It inherits nodriver's stealth defaults.
- Leaks and risks:
  - The README gives no list of leaks, only "(almost) impossible to detect". Leaks such as `Runtime.enable` have to be checked at rung 1.
  - Being async only is the largest porting cost of the four.
- Evidence: self-reported (an example against BrowserScan).

## Rejected

- **nodriver**: maintained and widely used (5k stars), but async only. Zendriver's README says contributions to it are "heavily restricted" and that critical-bug PRs stay open for months. Zendriver takes its place, and testing nodriver as well would add nothing.
- **undetected-chromedriver**: last release 2024-02-17. Its author points to nodriver as the successor.
- **Camoufox**: built on Firefox. It cannot keep the Chrome profile that holds the trusted device.
- **DrissionPage**: its last release, 2026-05-27, sits exactly on the 6-month boundary. Its docs are mostly in Chinese, and its stealth claims are not documented. Reconsider it if a new release ships.
- **Botasaurus**: last PyPI release 2026-01-06, outside the window.
- **rebrowser-playwright**: maintained, but only 107 stars. It patches the same `Runtime.enable` leak as Patchright, which takes its place on this list.
- **playwright-stealth**: last release 2026-04-04. It injects JS evasions and does not fix protocol-level leaks. The map also rules out plain Playwright.

## What this does not settle

- No independent benchmark compares the four stacks on the same pages. Every pass list above is self-reported. Rung 1 (offline fingerprint pages, headless and headed) has to produce that comparison.
- Whether each stack keeps the package's current masking: the headless User-Agent token fix, `--lang`, the window size, and the CDP calls in `linkedin_jobs_scraper/utils/chrome_driver.py`. This is the hard gate in #139.
