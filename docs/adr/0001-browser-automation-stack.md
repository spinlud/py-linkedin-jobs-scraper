---
status: proposed
---

# Move the browser automation from Selenium to Patchright

The package drives the installed Chrome through Patchright, a fork of Playwright, instead of Selenium and chromedriver. The port is built on its own branch and replaces Selenium in a major version only if it passes the comparison below.

**Why.** On offline fingerprint pages, three detectors name Selenium a bot in every mode. The causes are chromedriver's `cdc_` globals and the `Runtime.enable` leak, and no Chrome flag can hide either. Patchright reads as a human on the same pages. Without chromedriver there is no chromedriver version skew and no split between urllib3 and WebDriver errors, and authenticated proxies become possible. LinkedIn does not tell the stacks apart today: one live search on a residential connection and one CI run on Azure runners gave the same results for Selenium, Patchright and Pydoll. So the gain is a margin against detection, not a fix for a current failure.

**Conditions.** Patchright stays clean only if:

- third-party storage partitioning stays on (its default `--disable-features` list is replaced without `ThirdPartyStoragePartitioning`);
- page scripts run in the isolated world only;
- the package's User-Agent masking is kept.

**Shape.** The code uses Playwright's API, with Patchright imported in one module, so falling back to plain Playwright is an import change at the cost of the stealth. The core is async with one browser and no `max_workers`, since more than one worker is discouraged because of LinkedIn's rate limiting.

**Comparison.** The port replaces Selenium when all three hold:

- `npm run test:e2e` passes on both;
- the offline fingerprint rung, rerun on the port, shows all three conditions holding;
- in live runs, the port gets no challenge that Selenium does not.

**Exits back to Selenium:**

- the port cannot keep the three conditions;
- `_is_session_lost` cannot be proven again with a cookie jar that covers the whole browser rather than the document on screen;
- in a live run, Patchright is challenged and Selenium is not.

## Considered options

- **Stay on Selenium.** Rejected: it is identifiable by any page that looks for chromedriver, and it cannot authenticate to a proxy.
- **Pydoll**, through its native API or its Playwright-compatible layer. It was the cleanest offline with no conditions. Rejected because it is async-only, navigation through an authenticated proxy hangs (an open issue), persistent profiles are undocumented, and it has one main author.
- **SeleniumBase (UC or pure CDP mode) and Zendriver.** Ruled out by the offline rung: each adds a detectable signal.
- **Plain Playwright.** It does not have Patchright's stealth patches.

## Consequences

- **CI challenges depend on the runner's network, not on the stack.** Selenium, Patchright and Pydoll all got a session on Azure runners. A reCAPTCHA came only from an AWS runner. Earlier notes that Selenium is challenged on every CI run did not record the network.
- **Patchright's Python port rests on one maintainer.** The fallback to plain Playwright keeps the API and loses only the stealth.
- **`chrome_options` and `chrome_executable_path` are replaced** with no compatibility shim.
- **Headless Chrome reports an 800x600 screen on every stack.** The move does not fix it.

The evidence is on the issue [Map: choose the browser-automation stack](https://github.com/spinlud/py-linkedin-jobs-scraper/issues/139) and its tickets.
