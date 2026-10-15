# Changelog

Notable releases of `linkedin-jobs-scraper` are recorded here, in the format of
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [8.0.0] - Unreleased

### Changed

- **Breaking:** a chromedriver on `PATH` is no longer used implicitly. Without an explicit path, a
  chromedriver matching the installed Chrome (or `chrome_binary_location`) is resolved through
  Selenium Manager and cached in `~/.cache/selenium`. The first run needs network access to fetch
  the driver.
- To keep using a specific chromedriver (e.g. in Docker images, or a distro `chromium-driver`),
  pass `--chrome-executable-path` on the CLI or `chrome_executable_path=` in `LinkedinScraper`; it
  is used as given, with no version check.
- Requires `selenium>=4.51.0`.

### Added

- `ChromedriverResolutionException` (in `linkedin_jobs_scraper.exceptions`), raised when a
  matching chromedriver cannot be obtained.

Releases before 8.0.0 are not recorded here; see the
[git history](https://github.com/spinlud/py-linkedin-jobs-scraper/commits/master).
