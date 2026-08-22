"""Kill the session in the middle of a run and check the scraper rebuilds it.

Not collected by pytest (the filename does not match `test_*.py`): it deliberately breaks a
live session, so it is a manual diagnostic rather than part of the suite.

A session retired part way through a run is the case a long run actually meets, and waiting
for LinkedIn to retire one takes about a hundred job loads and cannot be told apart from
throttling. So the retirement is provoked instead, by emptying the browser's jar of both
`li_at` and `li_rm`, which leaves it in exactly the state a refusal leaves it in: holding
nothing that will authenticate the next request. Both have to go - with `li_rm` left in
place LinkedIn mints a replacement session on the next authenticated route by itself, and
the ladder under test is never reached. The credential the scraper was given is untouched,
so recovery has the same material to work with as it would in the wild.

The deletion is monkey-patched onto the strategy's private methods, name mangled, so that no
test hook exists in the shipped code.

Requires the remember me pair: a bare `LI_AT_COOKIE` cannot be renewed, and there would be
nothing to recover with. PYTHONPATH is required when running the file by path, which puts
its own directory on sys.path rather than the one holding the package.

    LI_RM_COOKIE=... LI_BCOOKIE=... PYTHONPATH=. python -u tests/manual/mid_run_recovery.py

Modes, one per gap being closed:

    paginate  retire the session before the second pagination, so the next page is requested
              without one and pagination fails. The run must finish complete, having had a
              session reissued.
    midpage   retire it in the middle of a page, failing that job, so the page has to be
              re-opened with some of its jobs already delivered. The run must finish
              complete and emit no job twice.
    every     retire it before every pagination. The run must give up within
              MAX_SESSION_RECOVERIES and say so, rather than spin.

Environment:
    LI_RM_COOKIE  the remember me credential, with LI_BCOOKIE
    LI_BCOOKIE    the browser id it was issued to
    MODE          paginate | midpage | every, default 'paginate'
    LIMIT         jobs to scrape, default 60 (three pages), 100 in every mode so that a
                  third pagination exists for the cap to be reached on
    SLOW_MO       seconds between jobs, default 1.0. Higher than the package default on
                  purpose: an HTTP 429 ends the run the same way a lost session does, and
                  the two are hard to tell apart in the result
    QUERY         search keywords, default 'Software Engineer'
    LOCATION      search location, default 'United Kingdom'
"""
import logging
import os
import sys

from linkedin_jobs_scraper import LinkedinScraper
from linkedin_jobs_scraper.config import Config
from linkedin_jobs_scraper.events import Events, EventData, EventMetrics, EventSession
from linkedin_jobs_scraper.exceptions import InvalidCookieException
from linkedin_jobs_scraper.query import Query, QueryOptions
from linkedin_jobs_scraper.strategies import AuthenticatedStrategy
from linkedin_jobs_scraper.utils.session import REMEMBER_COOKIE_NAME, SESSION_COOKIE_NAME

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)-7s %(message)s')
logging.getLogger('urllib3').setLevel(logging.WARN)
logging.getLogger('selenium').setLevel(logging.WARN)

# The page dumps that name a 429 are logged at debug, and telling throttling apart from a
# lost session is the whole point of the run. They go to the spy, not to the console.
logging.getLogger(Config.LOGGER_NAMESPACE).setLevel(logging.DEBUG)

for handler in logging.getLogger().handlers:
    handler.setLevel(logging.INFO)

MODE = os.environ.get('MODE', 'paginate').lower()

# The cap is reached on the third recovery, so every mode needs a fourth page to reach it
LIMIT = int(os.environ.get('LIMIT', '100' if MODE == 'every' else '60'))
SLOW_MO = float(os.environ.get('SLOW_MO', '1.0'))
QUERY = os.environ.get('QUERY', 'Software Engineer')
LOCATION = os.environ.get('LOCATION', 'United Kingdom')

# The job of the page the midpage mode kills the session on. Late enough that the page has
# delivered several jobs, so re-opening it would emit them twice if nothing guarded that.
MIDPAGE_JOB_INDEX = 30

# What the strategy logs when LinkedIn mints a session, which is the recovery having worked
SESSION_ISSUED_MESSAGE = 'Session issued by LinkedIn'
RECOVERY_CAPPED_MESSAGE = 'recoveries, skip'

# Throttling ends a run early too, and a short run means nothing if this is why
THROTTLED_MESSAGE = 'ERROR 429'

records = []
metrics_seen = []
errors = []
invalid_session_events = 0
refreshed_sessions = []
retirements = 0


class LogSpy(logging.Handler):
    """Keep every message the package logs, so the run can be asserted on afterwards."""

    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())

    def count(self, needle: str) -> int:
        return len([m for m in self.messages if needle in m])


log_spy = LogSpy()
logging.getLogger(Config.LOGGER_NAMESPACE).addHandler(log_spy)


def retire_session(driver) -> None:
    """Leave the browser holding nothing that will authenticate its next request."""

    global retirements

    for name in (SESSION_COOKIE_NAME, REMEMBER_COOKIE_NAME):
        try:
            driver.delete_cookie(name)
        except BaseException as e:
            print(f'>>> failed to delete {name}: {e}')

    retirements += 1
    print(f'>>> retired the session in the browser (retirement {retirements})')


def patch_paginate(every: bool) -> None:
    """
    Retire the session before a pagination, so the next page is requested without one

    :param every: bool retire before every pagination, rather than only the second
    """

    original = AuthenticatedStrategy._AuthenticatedStrategy__paginate
    calls = {'n': 0}

    def patched(driver, url, tag, **kwargs):
        calls['n'] += 1

        if every or calls['n'] == 2:
            retire_session(driver)

        return original(driver, url, tag, **kwargs)

    AuthenticatedStrategy._AuthenticatedStrategy__paginate = staticmethod(patched)


def patch_load_job_details() -> None:
    """
    Retire the session in the middle of a page and fail that job

    A cookie taken out of the jar does not stop the page already rendered from being read,
    so a job has to be failed as well for the strategy to look at the session at all - which
    is what a job failing on a dead session does in the wild.
    """

    original = AuthenticatedStrategy._AuthenticatedStrategy__load_job_details
    calls = {'n': 0}

    def patched(driver, job_id, **kwargs):
        calls['n'] += 1

        if calls['n'] == MIDPAGE_JOB_INDEX:
            retire_session(driver)
            raise RuntimeError('provoked failure on a job whose session has just been retired')

        return original(driver, job_id, **kwargs)

    AuthenticatedStrategy._AuthenticatedStrategy__load_job_details = staticmethod(patched)


def on_data(data: EventData) -> None:
    records.append(data)


def on_metrics(metrics: EventMetrics) -> None:
    metrics_seen.append(str(metrics))


def on_error(err) -> None:
    errors.append(str(err))


def on_invalid_session() -> None:
    global invalid_session_events
    invalid_session_events += 1


def on_session_refreshed(session: EventSession) -> None:
    refreshed_sessions.append(session.li_at)


def report() -> int:
    """Print what happened and return the exit code."""

    job_ids = [r.job_id for r in records]
    duplicates = sorted({i for i in job_ids if job_ids.count(i) > 1})
    sessions_issued = log_spy.count(SESSION_ISSUED_MESSAGE)
    capped = log_spy.count(RECOVERY_CAPPED_MESSAGE)
    throttled = log_spy.count(THROTTLED_MESSAGE)

    print('\n================ RESULT ================')
    print(f'mode                 : {MODE}')
    print(f'records              : {len(records)} / {LIMIT}')
    print(f'duplicate job ids    : {len(duplicates)} {duplicates if duplicates else ""}')
    print(f'sessions retired     : {retirements}')
    print(f'sessions issued      : {sessions_issued}')
    print(f'recovery cap reached : {capped}')
    print(f'429 pages seen       : {throttled}')
    print(f'INVALID_SESSION      : {invalid_session_events}')
    print(f'SESSION_REFRESHED    : {len(refreshed_sessions)}')
    print(f'ERROR events         : {len(errors)}')

    for line in metrics_seen:
        print(f'metrics              : {line}')

    failures = []

    if duplicates:
        failures.append(f'{len(duplicates)} job ids were emitted more than once')

    if invalid_session_events:
        failures.append('INVALID_SESSION fired although a session was reissued')

    if not retirements:
        failures.append('the session was never retired, so nothing was exercised')

    if MODE == 'every':
        # Every page is requested without a session, so the run is meant to stop early
        if not capped:
            failures.append('the recovery cap was never reached and never reported')
    else:
        if len(records) != LIMIT:
            failures.append(f'expected {LIMIT} records, got {len(records)}')

        if not sessions_issued:
            failures.append('no session was ever reissued, so no recovery took place')

        if not refreshed_sessions:
            failures.append('SESSION_REFRESHED never fired, so the caller cannot store the new session')
        elif refreshed_sessions[-1] == Config.LI_AT_COOKIE:
            failures.append('SESSION_REFRESHED carried the session that was supplied, not a new one')

    if failures:
        print('\nFAILED')
        for failure in failures:
            print(f'  - {failure}')

        if throttled:
            print('\n  LinkedIn served a 429 during this run, which ends it early for reasons '
                  'that have nothing to do with the session. Raise SLOW_MO, wait, and run it '
                  'again before reading anything into the above.')

        return 1

    print('\nPASSED')
    return 0


def main() -> int:
    if not Config.LI_RM_COOKIE or not Config.LI_BCOOKIE:
        print('LI_RM_COOKIE and LI_BCOOKIE are both required: a session that cannot be '
              'reissued has nothing to recover with. Get them from a machine with a display:\n'
              '  linkedin-jobs-scraper login --chrome-user-data-dir <path>')
        return 2

    if MODE not in ('paginate', 'midpage', 'every'):
        print(f'Unknown MODE {MODE!r}, expected one of paginate, midpage, every')
        return 2

    if MODE == 'midpage':
        patch_load_job_details()
    else:
        patch_paginate(every=MODE == 'every')

    scraper = LinkedinScraper(headless=True, max_workers=1, slow_mo=SLOW_MO, page_load_timeout=40)

    scraper.on(Events.DATA, on_data)
    scraper.on(Events.METRICS, on_metrics)
    scraper.on(Events.ERROR, on_error)
    scraper.on(Events.INVALID_SESSION, on_invalid_session)
    scraper.on(Events.SESSION_REFRESHED, on_session_refreshed)

    try:
        scraper.run(Query(
            query=QUERY,
            options=QueryOptions(locations=[LOCATION], limit=LIMIT, apply_link=False)))
    except InvalidCookieException as e:
        print(f'\nInvalidCookieException aborted the run: {e}')
        report()
        return 1

    return report()


if __name__ == '__main__':
    sys.exit(main())
