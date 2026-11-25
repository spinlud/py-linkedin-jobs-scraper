# AGENTS.md

`linkedin-jobs-scraper` is a PyPI library and CLI that scrapes LinkedIn jobs through an authenticated headless Chrome. The entry points are the scripts in `package.json`. A sibling npm package aims for feature parity.

## Every change

- Work on a branch and open a PR. `npm run check` must pass first. `npm run hooks`, once per clone, makes every push run the check.
- A behaviour change comes with a test that fails without it, and with a CHANGELOG line when users can see it.
- Comments are in English and describe the code as it is now. Why it changed goes in the commit message.
- A new filter also goes in the CLI and the README; a new `EventData` field in the README and `tests/shared.py`.

## Only when the user asks

- Run anything that reaches LinkedIn.
- Push a `v*` tag, run `npm run release`, approve a deployment, or edit the master ruleset or the `pypi` environment. A `v*` tag starts a release to PyPI.

## Working with LinkedIn

Most of these fail silently or cost the account, and offline tests stay green.

- **Look like a person's browser.** Each Chrome flag, CDP call and request is something LinkedIn can detect. Use the page as a person would, and never call LinkedIn's internal endpoints. Keep the defaults `max_workers=1` and `slow_mo=0.8`.
- **Absence proves nothing.** The driver does not wait for pages (`page_load_strategy='none'`) and the cookie jar is that of the document on screen, so a missing element or cookie often means "not yet" or "throttled". Wait for a positive sign, and judge a lost session only with `__is_session_lost`.
- **A job is its id, never its position.** The list streams in and re-renders.
- **Anchor on meaning.** Class names are generated: use `componentkey`, `data-testid`, `aria-label`, `href` paths and text shapes. Page scripts return raw strings; Python parses them, tested with strings captured live.
- **Capture, don't guess.** Selectors, filter codes and URL parameters come from a real page, and a new filter is proven by comparing live results with and without it.

## Live runs

`npm run test:e2e` uses the signed-in profile (`LI_CHROME_USER_DATA_DIR=~/.lijs/chrome-profile`). One browser at a time: Chrome locks a profile. Each search changes the account's remembered location, so finish with one search on its usual location. A failure usually means LinkedIn changed its page.

## Review

Before opening a PR that changes code, review the diff against `origin/master` in a fresh context (Claude Code: `/code-review`). Findings advise: fix the real ones and say in the PR why the others stay. One round is enough.

1. Does a test fail without this change?
2. Does it rebuild something this package, the standard library or Selenium already has?
3. Is each new class, parameter or layer needed by code that exists today?
4. Can an error be swallowed, or turned into an empty value that looks like an answer?
5. Do the comments, README and CHANGELOG match the code as it is now?
