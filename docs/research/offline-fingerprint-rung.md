# Offline fingerprint rung

Run on 2026-11-27 for the ticket [Offline fingerprint rung](https://github.com/spinlud/py-linkedin-jobs-scraper/issues/144).

- **Setup:** the installed Google Chrome 158 on a residential connection.
- **Profiles:** each run used a fresh throwaway profile.
- **LinkedIn:** nothing was sent to LinkedIn.

The harness is in [`offline-fingerprint-rung/`](offline-fingerprint-rung/):

- `rung.py` runs one stack in one mode against every page.
- `runall.sh` runs the whole matrix.
- `summarize.py` reduces the raw results to `summary.json`.
- `tpsp.py` is the Patchright follow-up described below.
- `summary.json` holds the signals each page reported. The raw page text and the screenshots are not committed: they carry details of the machine and the connection.

## What was run

The harness covers six stacks in three modes each, 18 runs in all. Every run launched and loaded every page.

**Stacks:**

- **Selenium:** the package itself, through `build_driver` and `mask_headless_user_agent`.
- **Patchright** 1.64.4, with `channel="chrome"`, `no_viewport=True`, and evaluation in the default isolated world.
- **SeleniumBase** 4.56.2 in two modes:
  - **UC mode:** `Driver(uc=True)`, loading pages with `uc_open_with_reconnect`;
  - **pure CDP mode:** `sb_cdp.Chrome`.
- **Pydoll** 3.0.1.
- **Zendriver** 0.18.0.

All candidates got `--use-mock-keychain --password-store=basic --lang=en-GB --window-size=1472,828` on top of their own defaults.

**Modes:**

- `headed`.
- `headless-raw`: no User-Agent masking.
- `headless-masked`: what the package does today.
  - It launches with `--user-agent=<UA without HeadlessChrome>`.
  - On the first secure page it calls `Network.setUserAgentOverride` with the browser's own client-hint metadata.

**Pages:**

- httpbin headers;
- bot.sannysoft.com;
- bot-detector.rebrowser.net. On this page:
  - the page's own triggers are called: `getElementById('detections-json')`, `getElementsByClassName('div')` and `window.dummyFn()`;
  - Patchright runs them twice, first isolated and then in the main world;
- deviceandbrowserinfo.com/are_you_a_bot;
- fingerprintjs BotD;
- CreepJS;
- browserscan.net/bot-detection.

## Results

**Verdict pages:**

- **BotD** shows `bot:<kind>` or `human`.
- **deviceandbrowserinfo** (DABI) shows `BOT` or `human`, with the flags it raised.
- **BrowserScan** (BS) shows `Robot` or `Normal`.
- **CreepJS** shows three percentages, in the order "like headless", "headless", "stealth".

**rebrowser column:** every red test, apart from `mainWorldExecution`. The harness trips that test itself by calling the page's trigger from the main world, so it reads red for every stack that cannot evaluate in an isolated world. It is discussed below.

| Stack | Mode | BotD | DABI | BS | CreepJS | rebrowser red | Other |
|---|---|---|---|---|---|---|---|
| Selenium | headless-raw | selenium | BOT: botUA, SeleniumChromeDefault, CDP | Robot | 31/67/0 | runtimeEnableLeak, headless UA | `cdc_` globals, screen 800x600, UA header `HeadlessChrome`, no WebGL |
| Selenium | headless-masked | selenium | BOT: SeleniumChromeDefault, CDP, timing | Robot | 31/0/0 | runtimeEnableLeak | `cdc_` globals, screen 800x600, no WebGL |
| Selenium | headed | selenium | BOT: SeleniumChromeDefault, CDP, timing | Robot | 25/0/0 | runtimeEnableLeak | `cdc_` globals, no WebGL |
| Patchright | headless-raw | headless_chrome | BOT: botUA | Robot | 38/67/0 | headless UA, storagePartitioning | screen 800x600, UA header `HeadlessChrome` |
| Patchright | headless-masked | human | human | Normal | 38/0/0 | storagePartitioning | screen 800x600 |
| Patchright | headed | human | human | Normal | 31/0/0 | storagePartitioning | none |
| SB UC | headless-raw | human | human | Normal | 38/0/0 | runtimeEnableLeak, ipcFloodingProtection | `cdc_` globals, screen 800x600 |
| SB UC | headless-masked | human | human | Normal | 38/0/0 | runtimeEnableLeak, ipcFloodingProtection | `cdc_` globals, screen 800x600 |
| SB UC | headed | human | human | Normal | 31/0/0 | runtimeEnableLeak, ipcFloodingProtection | a `cdc_` global |
| SB CDP | headless-raw | human | BOT: inconsistent worker values | Normal | 38/33/0 | platformMismatch (empty brands), ipcFloodingProtection | `Sec-Ch-Ua` header empty, screen 800x600 |
| SB CDP | headless-masked | human | human | Normal | 38/33/0 | platformMismatch (empty brands), ipcFloodingProtection | `Sec-Ch-Ua` header empty, screen 800x600 |
| SB CDP | headed | human | BOT: inconsistent worker values | Normal | 25/0/0 | ipcFloodingProtection | none |
| Pydoll | headless-raw | headless_chrome | BOT: botUA | Robot | 31/67/0 | headless UA | screen 800x600, UA header `HeadlessChrome` |
| Pydoll | headless-masked | human | human | Normal | 31/0/0 | none | screen 800x600 |
| Pydoll | headed | human | human | Normal | 25/0/0 | none | none |
| Zendriver | headless-raw | human | human | Normal | 31/33/0 | workerConsistency (Worker brands differ) | screen 800x600 |
| Zendriver | headless-masked | human | human | Normal | 31/0/0 | workerConsistency (Worker brands differ) | screen 800x600 |
| Zendriver | headed | human | human | Normal | 25/0/0 | none | none |

Sannysoft failed no row for any stack in any mode, so it does not tell them apart.

## Findings

1. **Selenium is the weakest stack on these pages.** Three detectors (BotD, DABI and BrowserScan) name it as Selenium or a bot in every mode, headed included.
   - **Cause:** chromedriver's `cdc_adoQpoasnfa76pfcZLmcfl_*` globals and the `Runtime.enable` leak (the CDP flag on DABI, `runtimeEnableLeak` on rebrowser).
   - **The package's flags cannot hide either.** Both come from chromedriver and from the CDP domains it enables.
2. **The User-Agent masking is still needed on every stack.** Without it, headless Patchright and Pydoll are flagged by BotD (`headless_chrome`), DABI and BrowserScan, and CreepJS rates them 67% headless. With the package's masking applied, all three verdicts turn clean and CreepJS reads 0%.
   - **Patchright's README advises against a custom User-Agent, but that advice does not hold here.** In headless mode, masking is what keeps it clean.
   - **SB CDP and Zendriver apply their own User-Agent handling in headless.** It leaves traces that the package's CDP override does not fix:
     - SB CDP sends an empty `Sec-Ch-Ua` header and empty `userAgentData.brands`;
     - Zendriver's Web Workers report different brands from the page.
3. **Main-world evaluation in Patchright is detectable** (the question carried over from [Stability and features of each candidate](https://github.com/spinlud/py-linkedin-jobs-scraper/issues/143)).
   - **Isolated world, the default:** no rebrowser trigger fires.
   - **`isolated_context=False`:** two tests turn red. `mainWorldExecution` fires, and `sourceUrlLeak` fires because the error stack carries a `UtilityScript` frame.
   - **So page scripts must stay in the isolated world.** A script that needs page globals is visible to any page that watches for it.
   - **The other stacks:** Selenium, Pydoll, Zendriver and SeleniumBase evaluate in the main world by default and trip `mainWorldExecution` in the same way. Selenium does this today, so for them it is not a regression.
4. **Patchright's one new signal can be removed.** Patchright turns off third-party storage partitioning by default (`--disable-features=...ThirdPartyStoragePartitioning...`, inherited from Playwright), and rebrowser's `storagePartitioning` test flags it.
   - **The fix, tested in `tpsp.py`:** launch with `ignore_default_args=[<that flag>]` and pass the same list again without `ThirdPartyStoragePartitioning`.
   - **The result:** headed Patchright then shows no red or yellow test on rebrowser.
5. **Headless Chrome reports an 800x600 screen on every stack, Selenium included.** rebrowser marks it yellow. It is not a regression for any candidate. It is a shared leak that `--window-size` does not change.
6. **No WebGL in the Selenium rows is the package's own doing.** It comes from its `--disable-gpu` flag, not from Selenium. The candidates ran without that flag and expose the real GPU.

## Pydoll's Playwright-compatible layer

A follow-up run, the `pydoll-pw` stack in `rung.py`, tested `pydoll.playwright.async_api`. It uses `launch_persistent_context` with `executable_path` pointing at the installed Chrome.

**It matches native Pydoll on every page and in every mode:**

| Mode | BotD | DABI | BS | CreepJS |
|---|---|---|---|---|
| headless-raw | headless_chrome | BOT | Robot | 31/67/0 |
| headless-masked | human | human | Normal | 31/0/0 |
| headed | human | human | Normal | 25/0/0 |

**Its injected selector engine trips nothing.** The engine runs in an isolated world. The run counted 60 cells on rebrowser with `page.locator('td').count()`, and no rebrowser test turned red or yellow.

**Two gaps, unlike Patchright:**
- `page.evaluate` runs in the main world, with no `isolated_context` option. That is the same as Selenium today, so it is not a regression.
- There is no `new_cdp_session`. Raw CDP, which the User-Agent override needs, goes through `page.tab.execute_command`.

## Which candidates go to the live rung

The gate: no lost masking and no automation signal that Selenium does not already show, in the configurations the package uses (headless with masking, and headed for login).

| Stack | Gate | Why |
|---|---|---|
| **Pydoll** | **Pass** | Clean in headless-masked and headed, through the native API or the Playwright-compatible layer. Every signal Selenium shows today is gone, apart from the shared 800x600 screen. |
| **Patchright** | **Pass, with conditions** | Clean once storage partitioning is left on (finding 4), page scripts stay in the isolated world (finding 3), and the package keeps its User-Agent masking (finding 2). |
| SeleniumBase UC | Fail | It keeps a `cdc_` global and the `Runtime.enable` leak, and adds `ipcFloodingProtection`. It also removes no failure class, per [Stability and features of each candidate](https://github.com/spinlud/py-linkedin-jobs-scraper/issues/143). |
| SeleniumBase CDP | Fail | Adds signals: an empty `Sec-Ch-Ua` and empty brands in headless, inconsistent Worker values (DABI) in headed, and `ipcFloodingProtection`. |
| Zendriver | Fail | In headless (the package's default), Web Workers report different brands from the page. That is a new signal, even with the package's masking. |

## Limits

- These pages test fingerprints only, not IP reputation or behaviour, and LinkedIn's own checks are unknown. The verdicts above are necessary but not sufficient, which is what the live rung is for.
- Each stack was run once per mode on one machine. CreepJS percentages vary by a few points between runs.
- **The candidates did not get the package's full flag list.** That list includes `--disable-gpu`, `--no-sandbox` and `--ignore-certificate-errors`, which are choices independent of the stack.
- **Only the headed run of the Patchright follow-up (`tpsp.py`) was repeated.**
