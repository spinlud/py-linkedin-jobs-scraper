# Live local spike on LinkedIn

Run on 2026-11-27 for the ticket [Live local spike on LinkedIn](https://github.com/spinlud/py-linkedin-jobs-scraper/issues/145), at the user's request.

- **Setup:** the installed Google Chrome 158, a residential connection, the signed-in profile `~/.lijs/chrome-profile`. Every run was headless with the package's User-Agent masking.
- **Search:** `python` in Italy (geoId 103350119), the account's usual location, so no extra search was needed to put the remembered location back.
- **Order and spacing:** Selenium, then Patchright, then Pydoll, each about a minute after the previous one closed.

The harness is [`live-spike/spike.py`](live-spike/spike.py). Its per-run results are not committed: they carry details of the account and the machine.

- **Selenium** is the package itself: `LinkedinScraper.run` with `limit=5`, `max_workers=1`, `slow_mo=0.8`.
- **The candidates** follow the package's sequence through the Playwright API, with the import swapped:
  - open the home page;
  - send `Network.setUserAgentOverride` with the browser's own client hints;
  - open the search page;
  - click the first five job cards and read each "About the job" section.
- **Patchright** ran as it passed the offline rung. Storage partitioning was left on, confirmed on the launch command line, and every script ran in the isolated world.
- **Pydoll** ran through `pydoll.playwright.async_api`. It sent the override through `page.tab.execute_command`.
- **Both candidates** launched the installed Chrome with `--use-mock-keychain --password-store=basic`, and the saved session decrypted.

## Results

| Stack | Session | Challenge | Search page | Jobs read | Time |
|---|---|---|---|---|---|
| Selenium | kept (`end`, no `invalid_session`) | none | 5 jobs, limit reached | 5 of 5 with descriptions | about 1 min |
| Patchright | kept (`li_at`, feed then search) | none | 25 jobs | 3 distinct jobs, all with descriptions | 16 s |
| Pydoll (Playwright layer) | kept (`li_at`, feed then search) | none | 25 jobs | 5 of 5 with descriptions | 20 s |

All three runs got the same first five jobs, in the same order, from 4491711156 to 4472556616.

The candidates' description lengths came within about 25 characters of Selenium's. The difference comes from reading `inner_text` instead of the package's parsing.

The Patchright row is short because of the harness, not the stack:

- each card's `componentkey` appears twice on the page, so the run opened two jobs twice;
- one description was read before its text had rendered.

Both bugs were fixed before the Pydoll run.

## Verdict

**No stack got a challenge, a lost session or a degraded result that the others did not.** Neither candidate fails this rung, so both go on to the CI run. That is where Selenium is challenged on every run, so it is the rung that can tell them apart.

## Limits

- One search per stack, three in about five minutes, on an account with a long-trusted device. A single clean run does not prove a stack is safe; a challenge would have counted against it.
- The candidates were driven by a short script, not by a port of the package. Pacing, scrolling and pagination were not exercised.
