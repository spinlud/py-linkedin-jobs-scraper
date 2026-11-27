# Chrome or Chromium for the signed-in profile

Research for issue #141 (map #139). Question: should the chosen stack drive the installed
Google Chrome or a Chromium build (Playwright/Patchright bundled Chromium, Chrome for
Testing, chromium-headless-shell), given that `~/.lijs/chrome-profile` was created by Chrome?

## Answer

Drive the installed **Google Chrome** (Patchright: `channel="chrome"`), the same browser
that writes the profile today. Reasons, strongest first:

1. **Profile version.** The profile is stamped with the version of the Chrome
   that last opened it (`Last Version`). Chromium refuses or warns on a profile written by a
   newer version (user-data downgrade, see below), and a bundled Chromium pinned by a
   Patchright release lags stable Chrome. Using the same channel removes the skew.
2. **Fingerprint parity.** Branded Chrome reports the `Google Chrome` brand in
   `Sec-CH-UA`/`navigator.userAgentData`, ships proprietary codecs, and runs the "new
   headless" which is the real browser. Bundled Chromium reports `Chromium`, lacks the
   codecs, and Playwright's default headless is the separate headless shell. Each of these
   differs from what the account has seen so far, which the map's hard gate forbids.
3. **Patchright recommends it.** Its README: "We recommend using Google Chrome instead of
   Chromium", with the undetected config `launch_persistent_context(user_data_dir=...,
   channel="chrome", headless=False, no_viewport=True)` and "do NOT add custom browser
   headers or user_agent".

Cookie decryption is **not** the blocker the question feared, because of the mock keychain
(next section), but it becomes one if a stack drops `--use-mock-keychain`.

## Cookie encryption keys

### Branded names differ (Chromium source)

- macOS, `components/os_crypt/common/keychain_password_mac.mm`:
  `GOOGLE_CHROME_BRANDING` uses Keychain service `"Chrome Safe Storage"`, otherwise
  `"Chromium Safe Storage"`.
- Linux, `components/os_crypt/async/browser/freedesktop_secret_key_provider.h`:
  Chrome uses KWallet folder `"Chrome Keys"`, key `"Chrome Safe Storage"`, app `"chrome"`;
  Chromium uses `"Chromium Keys"`, `"Chromium Safe Storage"`, `"chromium"`.
- Linux `basic` store, `components/os_crypt/async/browser/posix_key_provider.cc`: tag
  `v10`, key `PBKDF2-HMAC-SHA1(1 iteration, key = "peanuts", salt = "saltysalt")`, the same
  for every brand.
- Linux backend selection (`docs/linux/password_storage.md`): auto-detected from the
  desktop, overridable with `--password-store=gnome-libsecret|kwallet|kwallet5|kwallet6|basic`,
  falling back to `basic` when none is available (the Docker/CI case).

So a profile written with the real OS key store by Chrome is unreadable to Chromium: the
cookies are there but fail to decrypt, and the session looks lost.

### Why it does not bite this project

Both automation stacks launch with a fixed, brand-independent key store:

- chromedriver `chrome/test/chromedriver/chrome_launcher.cc`, `kDesktopSwitches`:
  `"password-store=basic"`, `"use-mock-keychain"`.
- Playwright `packages/playwright-core/src/server/chromium/chromiumSwitches.ts`:
  `'--password-store=basic'`, `'--use-mock-keychain'`.

The package only excludes `enable-automation` (`linkedin_jobs_scraper/utils/chrome_driver.py`),
and `lijs login` also goes through `build_driver`, so `~/.lijs/chrome-profile` has always
been written with the mock keychain on macOS and the `basic` store on Linux. Its cookies
decrypt in any Chromium-family browser launched with the same switches, Chrome or
Chromium. Consequences:

- A Patchright/Playwright stack keeps the session as long as it keeps those two switches
  (it does by default; Patchright's switch patches should be checked in the spike).
- Removing `--use-mock-keychain` (e.g. "to look more like a person") would switch to
  `Chrome Safe Storage` in the real Keychain and orphan every existing cookie. Not inferred
  as detectable by LinkedIn, but fatal to the session.
- A profile a user made by hand in their everyday Chrome (real Keychain) never worked
  with this package either; nothing changes there.

Not verified: the Keychain on this machine was not touched, and the profile was not opened
by any browser, as the ticket required.

## Profile version compatibility

Chrome writes `Last Version` into the user data dir
(`chrome/browser/downgrade/user_data_downgrade.h`, `kDowngradeLastVersionFile`) and on
start-up compares it with its own version; an older browser treats the dir as a downgrade
(on branded builds it moves the data aside; otherwise it shows the "profile from a newer
version" error). Opening a Chrome-158 profile with an older bundled Chromium therefore
risks losing or refusing the profile. A browser of the same or newer major is safe, which
the installed stable Chrome always is.

## Other points

- **Chrome 136+ remote debugging** (developer.chrome.com/blog/remote-debugging-port):
  `--remote-debugging-port` is ignored for the *default* user data dir. Not an issue: the
  package always passes a non-default `--user-data-dir`. Chrome for Testing keeps the old
  behaviour.
- **Codecs** (playwright.dev/docs/browsers): "Chromium does not have all the codecs that
  Google Chrome or Microsoft Edge are bundling". `canPlayType('video/mp4; codecs="avc1..."')`
  is a common fingerprint probe.
- **Headless** (playwright.dev/docs/browsers): Playwright ships a separate
  chromium-headless-shell for headless; new headless "is the real Chrome browser". Today the
  package uses `--headless=new` on Chrome and masks `HeadlessChrome/` in the UA; any stack
  must keep new headless, not the shell.
- **Linux/Docker**: Chrome is installable there (`patchright install chrome` or the Google
  apt repo, amd64 only); Chromium would only be needed on arm64, where branded Chrome for
  Linux is not published. Under `--password-store=basic` the profile is portable either way.

## Recommendation for the map

Drive the installed Google Chrome with a persistent context on the existing profile, keep
`--use-mock-keychain` and `--password-store=basic`, keep new headless. Treat bundled
Chromium, Chrome for Testing and headless shell as out for the signed-in run.
