# Changelog

Notable releases of `linkedin-jobs-scraper` are recorded here, in the format of
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [8.0.0] - 2026-10-16

### Changed

- **Breaking:** a chromedriver on `PATH` is no longer used implicitly. Without an explicit path, a
  chromedriver matching the installed Chrome (or `chrome_binary_location`) is resolved through
  Selenium Manager and cached in `~/.cache/selenium`. The first run needs network access to fetch
  the driver.
- To keep using a specific chromedriver (e.g. in Docker images, or a distro `chromium-driver`),
  pass `--chrome-executable-path` on the CLI or `chrome_executable_path=` in `LinkedinScraper`; it
  is used as given, with no version check.
- Requires `selenium>=4.51.0`.
- `lijs login` reports a chromedriver that cannot be obtained as a short error instead of a
  traceback.
- Without an explicit Chrome profile or cookie environment variables, the CLI and the library use
  the default Chrome profile `~/.lijs/chrome-profile` (created by `lijs login` with owner-only
  permissions), so `--chrome-profile` is optional for `lijs login`, `lijs jobs` and `lijs job`.
  A scrape never creates that profile: when it is missing, the run stops with an error asking to
  sign in first.
- The scraper logs, at `INFO` level, which session source each run uses, and the CLI shows it on
  the `session` line of the summary it prints before a run.
- `max_workers` defaults to `1`. The warning about a Chrome profile not being shareable by
  concurrent browsers fires only when more workers are asked for explicitly.
- When no usable session is available, the run emits `INVALID_SESSION` and raises
  `InvalidCookieException`, and `lijs jobs` / `lijs job` exit with code `2`, instead of finishing
  with no results and exit code `0`. That covers a Chrome profile, default or explicit, that is
  missing or empty while no cookie environment variable is set to seed it, refused before any
  browser opens, as well as a profile or cookie that yields no session once the browser is up.
- An explicit `chrome_user_data_dir` is applied also when custom `chrome_options` are passed,
  unless they set their own `--user-data-dir`.
- A failed or interrupted `lijs login` (or `sign_in()`) removes the profile directory it created;
  a directory that already existed is left alone. Ctrl-C during `lijs login` exits with code `130`
  without a traceback.

### Added

- `ChromedriverResolutionException` (in `linkedin_jobs_scraper.exceptions`), raised when a
  matching chromedriver cannot be obtained.
- `--chrome-profile` CLI option for the Chrome profile directory, an alias of
  `--chrome-user-data-dir`.

### Fixed

- Log messages render as plain text instead of Python tuples (e.g.
  `('A Chrome profile cannot be shared ...',)`). Multiple arguments are joined with tabs, and each
  argument is truncated at 1000 characters on its own.
- Log records point at the calling function (`funcName`, `lineno`, `pathname`) instead of
  `utils/logger.py`.

Releases before 8.0.0 are not recorded here; see the
[git history](https://github.com/spinlud/py-linkedin-jobs-scraper/commits/master).
