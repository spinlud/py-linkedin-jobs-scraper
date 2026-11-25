# Changelog

Notable releases of `linkedin-jobs-scraper` are recorded here, in the format of
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed

- An exception in a `DATA` callback during a search reaches the caller of `run` as
  `CallbackException`, instead of becoming an `ERROR` event while the search goes on.
- Ctrl-C stops `scrape_job`, `sign_in` and `has_credentials`, instead of becoming an `ERROR` event or
  being swallowed.
- `KeyboardInterrupt` and `SystemExit` raised in a callback reach the caller as they are, instead of
  wrapped in `CallbackException`.
- A `company_jobs_url` without a company id says that it is invalid, instead of that it must be a
  valid url.

## [9.0.1] - 2026-11-24

### Changed

- **No location means the account's current location, and Worldwide is gone.** The new search page
  offers no worldwide search: `geoId=92000000`, no `geoId` and every other way of asking for one
  leave the location the account last searched applied. So a search without a location (the
  default when no `locations` are given) now sends no `geoId` and searches the account's current
  location, and an explicit `'Worldwide'` is warned and skipped. 9.0.0 sent `92000000`, which
  LinkedIn silently ignored.

### Added

- `EventBegin` and `EventData` carry `resolved_location`: the location LinkedIn applied to the
  search, read from the page (`''` when unreadable, and for a single job). The CLI shows it on the
  `📍` line when it differs from the requested one (`📍 San Franci → San Francisco Bay Area`), and
  jsonl, json and csv output include it.
- `EventBegin` carries the requested `location`, as `EventData` does.
- A location resolved by name is checked against the location LinkedIn applied to the results
  page, compared on the first comma-separated segment. On a mismatch the page is re-opened once,
  then the location is warned and skipped, rather than returning jobs from another place.
- `--location Remote` (or `locations=['Remote']`), which matches no place, now says remote work is a
  workplace type and points at `OnSiteOrRemoteFilters.REMOTE` / `--workplace remote`.

### Fixed

- With several locations, the CLI's `📍` lines no longer shift onto the wrong location after a
  skipped one: each section is labelled from its own `BEGIN` event instead of by position.

## [9.0.0] - 2026-11-23

LinkedIn replaced its jobs search page for every account, and 8.x returns no jobs against the new
one. 9.0.0 scrapes the new page. Its search contract is different, so several filters change or
go away.

### Migrating from 8.x

Filters (`linkedin_jobs_scraper.filters`, `QueryFilters`, and the `lijs jobs` flags):

| 8.x | 9.0.0 |
| --- | --- |
| `RelevanceFilters`, `relevance=`, `--relevance` | Removed: LinkedIn ignores the sort order. |
| `SalaryBaseFilters`, `base_salary=`, `--salary` | Removed: LinkedIn ignores the salary filter. |
| `IndustryFilters`, `industry=`, `--industry` | Removed: LinkedIn ignores the industry filter. |
| `JobFunctionFilters`, `job_function=`, `--job-function` | Removed. |
| `BenefitsFilters`, `benefits=`, `--benefits` | Removed. |
| `CommitmentsFilters`, `commitments=`, `--commitments` | Removed. |
| `TypeFilters.TEMPORARY`, `TypeFilters.OTHER` (`--type temporary`, `--type other`) | Removed: the new page has no such employment types. |
| `ExperienceLevelFilters.INTERNSHIP`, `.ASSOCIATE`, `.MID_SENIOR` (`--experience internship`, `associate`, `mid-senior`) | Replaced by LinkedIn's new scale: `ENTRY_LEVEL`, `SENIOR`, `MANAGER`, `DIRECTOR`, `EXECUTIVE`. For internships, use `TypeFilters.INTERNSHIP`. |
| `TypeFilters`, `ExperienceLevelFilters`, `OnSiteOrRemoteFilters` values | New codes, sent together in one `f_SAL` URL parameter instead of `f_JT`, `f_E` and `f_WT`. Code that uses the members by name keeps working. |
| `time`, `easy_apply`, `under_10_applicants`, `company_jobs_url` | Unchanged. |

A removed enum fails on import, a removed `QueryFilters` argument raises `TypeError`, and a
removed CLI flag or value exits with code 2. Keywords are never rewritten to stand in for a
removed filter.

The "In my network" filter is not implemented: how LinkedIn encodes it could not be observed.

Searches:

- **A search needs keywords.** The new page shows a landing page of suggested searches, not
  results, for a search without keywords, so `Query(query='')` (and `lijs jobs` without a query)
  now raises `ValueError`. A company search needs keywords as well.
- **Every search carries a `geoId`.** LinkedIn drops a free-text `location=` parameter, and a
  search without a location inherits the last location the account searched. No location now
  means Worldwide (`92000000`), and a location name is resolved to a `geoId` by the scraper (see
  *Added*). A run leaves the account's remembered location at the last one it searched.

`EventData` fields keep their names; these change meaning or precision:

| Field | 9.0.0 |
| --- | --- |
| `date` | Always approximated from `date_text`, at the precision the relative text gives. |
| `applicant_count` | The text LinkedIn shows, either `'N applicants'` or `'… people clicked apply'`. |
| `salary` | From the job's salary pill. |
| `insights` | The job's other pills (workplace type, employment type and similar tags), without the salary. |
| `benefits` | Only the names on the search result card's benefits pill. A `+N benefit(s)` remainder is dropped, a count-only pill gives `[]`, and a single job always gives `[]`. |
| `apply_link` | Decoded from the external apply link when there is one. Easy Apply jobs never carry one. |

`EventBegin.job_total` (`-1` when unreadable) is replaced by `total` (`None` when unreadable) and
`total_capped` (`True` for LinkedIn's "N+ results", where `total` is a lower bound).

### Added

- `QueryFilters(verified=True)` / `--verified`: only verified jobs (`f_VJ`).
- `QueryFilters(company_id='1441')` / `--company-id`: filter by a company id directly, as an
  alternative to `company_jobs_url` / `--company-jobs-url`.
- Location names are resolved through the location picker of LinkedIn's search page: the name is
  typed in and the `geoId` of LinkedIn's first suggestion is used. The match is logged at `INFO`,
  each name is looked up once per process, and a name with no suggestion is reported and skipped
  while the run's other locations still scrape. A numeric location, including
  `--location 103644278`, is taken as a `geoId`.

### Changed

- Every `EventData` field is read from LinkedIn's new jobs pages, through one detail extractor
  shared by search and `scrape_job` / `lijs job`.
- `scrape_job` / `lijs job` emit `NOT_FOUND` when LinkedIn says the job id is not valid or the
  posting was removed. A page that does not load, including one that stays throttled, is skipped
  without an event.

### Fixed

- `lijs -v` / `-vv` and `LOG_LEVEL` print the library's `INFO` / `DEBUG` logs on stderr. The
  library itself still installs no logging handler.

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
