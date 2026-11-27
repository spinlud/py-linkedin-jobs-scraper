# Authentication and sessions: reference library vs this package

Question: [#147](https://github.com/spinlud/py-linkedin-jobs-scraper/issues/147), child of map #139.

Sources, read only: the reference library (joeyism/linkedin_scraper, Playwright) at
`linkedin_scraper/core/auth.py`, `core/browser.py`, `core/utils.py`, `scrapers/base.py`,
`samples/create_session.py` and its git log (`55f2305`, `9b73575`, `7e8c2e1`: "use URL-based
detection in is_logged_in() to handle A/B tested DOM"); this package at `linkedin_jobs_scraper/login.py`,
`utils/session.py`, `utils/session_source.py`, `strategies/authenticated_strategy.py`, and the
local notes `docs/security-checkpoint-investigation.md` and `docs/ci-cookie-pair-investigation.md`.
Nothing was run.

## Verdict

Ours is better or equivalent on every point. The reference library's auth is a thin, optimistic
layer: it trusts the first URL it sees, swallows its own CAPTCHA error, and falls back to
"proceeding anyway" when it cannot confirm a session. Two small ideas are worth borrowing
(see the end); nothing structural.

## Point by point

| Point | Reference | Ours | Verdict |
|---|---|---|---|
| Login by credentials | `login_with_credentials` fills `#username`/`#password` and clicks submit (`auth.py`); an optional "warm-up" visits Google, Wikipedia and GitHub first | No automated password entry. `sign_in` (`login.py`) opens a visible browser on a persistent profile and waits for a human; `wait_for_session` polls for `li_at` away from the sign-in paths | **Ours better.** Typing a password with a bot is the most detectable act there is, and the checkpoint investigation showed a challenged account only recovers on a trusted device. The warm-up adds unrelated traffic with no evidence it helps |
| Manual login | `wait_for_manual_login` polls `is_logged_in` for 5 min; `create_session.py` saves `storage_state` | `sign_in` does the same into a persistent profile and prints the cookies | **Equivalent** in idea; ours also removes profile dirs it created when the sign in fails |
| Login by cookie | `li_at` only, on `.linkedin.com`, then `goto /feed` | `li_at` on `.www.linkedin.com` (the domain LinkedIn itself uses, `session.py`), or the remember-me pair `li_rm`+`bcookie` with a one-year max-age, so LinkedIn mints a fresh `li_at` | **Ours better.** `li_at` alone dies with the session; the pair renews. Our notes record that `li_rm` alone, or next to another browser's `bcookie`, is refused, which the reference does not model |
| Persistence | `storage_state` JSON (cookies + localStorage) saved and loaded into a fresh context (`browser.py` `save_session`/`load_session`) | Persistent Chrome profile (`LI_CHROME_USER_DATA_DIR`), env-var cookies as fallback (`session_source.py`) | **Ours better for LinkedIn.** The checkpoint investigation found a flagged account honours only the trusted device: the full profile passed, the same cookies injected into a fresh profile were challenged. `storage_state` is exactly "cookies into a fresh profile". It is more portable (one JSON file), which matters only if profiles are ever dropped |
| Logged-in detection | `is_logged_in`: URL not in a blocker list, then nav selectors (`.global-nav__primary-link`, `nav a[href*="/feed"]`, `button:has-text("Home")`) **or** URL on `/feed`, `/mynetwork`, ...; False on any exception | `li_at` in the jar of a document that is on LinkedIn (`_is_session_lost` = `is_on_linkedin and not li_at`), plus `_is_guest_page` judging the rendered page; an unreadable answer counts as "not lost" | **Ours better.** The reference reads "no nav yet" or an exception as logged out, and an authenticated-looking URL as logged in even on a guest page; its own log shows the selector half broke on an A/B test. Ours waits for a positive sign and refuses to read absence as loss |
| Lost session mid-run | `ensure_logged_in` raises `AuthenticationError`; no recovery | Authenticate again from the next source, emit `INVALID_SESSION` only when every source is refused, and skip rather than abort when the session holds but the page is throttled | **Ours better** |
| Checkpoint / challenge | URL contains `checkpoint`/`challenge`/`authwall`: raise with advice to log in manually. `detect_rate_limit` also looks for a CAPTCHA iframe and body text such as "too many requests", "try again later" | `/checkpoint/lg/login` is among the sign-in paths; no automated challenge solving (clicking reCAPTCHA escalates to an image grid, per the investigation); `_describe_page` reports what is on screen | **Mostly equivalent**, ours more careful. Reference bug: the CAPTCHA `RateLimitError` is raised inside `try: ... except Exception: pass` and so swallowed. Its body-text phrases are generic enough to match job descriptions |
| Rate pacing | `slow_mo=0` default, fixed sleeps, `retry_async` with backoff, `RateLimitError.suggested_wait_time` (30-60 min) | `slow_mo=0.8`, `max_workers=1`, one browser per profile; throttling told apart from session loss | **Ours better** on pacing. The reference's typed "wait this long" hint is a nicer error surface |

## Ideas worth borrowing

1. **A suggested wait on what we report when LinkedIn challenges or throttles us** (reference
   `RateLimitError(suggested_wait_time=...)`, `core/utils.py`). `_describe_page` already says what
   is on screen; adding "wait, then retry from the trusted profile" gives callers something to act
   on. Small and stack independent.
2. **Name the checkpoint apart from a refused session.** The reference raises a checkpoint error
   distinct from "cookie invalid" (`auth.py`). Ours folds `/checkpoint/` into the sign-in paths and
   ends in `InvalidCookieException`, which tells the user to fetch a new cookie when the fix is to
   pass the challenge in the persistent profile. Worth a distinct message, anchored on the
   checkpoint path as captured from a live page before use.

Not worth borrowing: credential login, browser warm-up, `storage_state` as the primary store,
selector- or URL-based logged-in checks, body-text rate-limit sniffing.
