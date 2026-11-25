#!/usr/bin/env python

import logging
import os

import pytest

from linkedin_jobs_scraper import LinkedinScraper
from linkedin_jobs_scraper.config import Config
from linkedin_jobs_scraper.events import Events
from linkedin_jobs_scraper.filters import (
    ExperienceLevelFilters,
    OnSiteOrRemoteFilters,
    TimeFilters,
    TypeFilters,
)
from linkedin_jobs_scraper.query import Location, Query, QueryFilters, QueryOptions

from .shared import on_begin, on_data, on_end, on_error, on_invalid_session, on_single_job_data


def _has_credentials() -> bool:
    if os.environ.get('LI_CHROME_USER_DATA_DIR'):
        return True
    if os.environ.get('LI_RM_COOKIE') and os.environ.get('LI_BCOOKIE'):
        return True
    return bool(os.environ.get('LI_AT_COOKIE'))


pytestmark = pytest.mark.skipif(
    not _has_credentials(),
    reason='no LinkedIn credentials in the environment (LI_RM_COOKIE + LI_BCOOKIE, LI_AT_COOKIE, or LI_CHROME_USER_DATA_DIR)',
)


# Job ids captured live from the search run, so the single-job test can target a
# currently-live posting rather than a hardcoded id LinkedIn may have removed.
captured_job_ids = []

# A name that matches no LinkedIn location
UNKNOWN_LOCATION = 'Xqzvplmw Nowhere'

# The (query, location) of every search in test_run that should find jobs
EXPECTED_SEARCHES = {
    ('Engineer', 'United Kingdom'),
    ('Software Engineer', 'United States'),
    ('Analyst', 'Germany'),
}


def test_run(caplog):
    # Change other logger levels
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('selenium').setLevel(logging.WARNING)

    scraper = LinkedinScraper(
        chrome_executable_path=None,
        chrome_options=None,
        chrome_user_data_dir=os.environ.get('LI_CHROME_USER_DATA_DIR'),
        headless=True,
        max_workers=1,
        slow_mo=0.8,
    )

    begin_events = []
    data_events = []
    error_events = []

    scraper.on(Events.BEGIN, on_begin)
    scraper.on(Events.BEGIN, lambda b: begin_events.append(b))
    scraper.on(Events.DATA, on_data)
    scraper.on(Events.DATA, lambda d: data_events.append(d))
    scraper.on(Events.ERROR, on_error)
    scraper.on(Events.ERROR, lambda e: error_events.append(e))
    scraper.on(Events.INVALID_SESSION, on_invalid_session)
    scraper.on(Events.END, on_end)

    queries = [
        Query(
            query='Engineer',
            options=QueryOptions(
                filters=QueryFilters(
                    company_jobs_url='https://www.linkedin.com/jobs/search/?f_C=1441%2C17876832%2C791962%2C2374003%2C18950635%2C16140%2C10440912&geoId=92000000',
                    time=TimeFilters.MONTH,
                    type=[TypeFilters.FULL_TIME, TypeFilters.INTERNSHIP, TypeFilters.CONTRACT],
                )
            ),
        ),
        Query(
            query='Software Engineer',
            options=QueryOptions(
                locations=[Location(geo_id='103644278', name='United States')],
                apply_link=True,
                limit=27,
                filters=QueryFilters(
                    time=TimeFilters.WEEK,
                    experience=ExperienceLevelFilters.SENIOR,
                    on_site_or_remote=[OnSiteOrRemoteFilters.ON_SITE],
                ),
            ),
        ),
        Query(
            query='Analyst',
            options=QueryOptions(
                locations=['Germany', UNKNOWN_LOCATION],
                skip_promoted_jobs=True,
                limit=3,
                filters=QueryFilters(
                    time=TimeFilters.MONTH,
                    verified=True,
                ),
            ),
        ),
    ]

    scraper.run(
        queries=queries,
        # Global options
        options=QueryOptions(
            locations=[Location(geo_id='101165590', name='United Kingdom')],
            limit=10,
        ),
    )

    captured_job_ids.extend(d.job_id for d in data_events)

    assert error_events == []
    assert {(d.query, d.location) for d in data_events} == EXPECTED_SEARCHES
    assert UNKNOWN_LOCATION not in {b.location for b in begin_events}
    assert any(
        r.name == Config.LOGGER_NAMESPACE
        and r.levelno == logging.WARNING
        and UNKNOWN_LOCATION in r.getMessage()
        for r in caplog.records
    )


def test_scrape_single_job():
    if not captured_job_ids:
        pytest.skip('no job id captured from the search test run')

    job_id = captured_job_ids[0]

    scraper = LinkedinScraper(
        chrome_executable_path=None,
        chrome_options=None,
        chrome_user_data_dir=os.environ.get('LI_CHROME_USER_DATA_DIR'),
        headless=True,
        max_workers=1,
        slow_mo=0.8,
    )

    data_events = []
    not_found_events = []
    error_events = []

    scraper.on(Events.DATA, on_single_job_data)
    scraper.on(Events.DATA, lambda d: data_events.append(d))
    scraper.on(Events.NOT_FOUND, lambda d: not_found_events.append(d))
    scraper.on(Events.ERROR, on_error)
    scraper.on(Events.ERROR, lambda e: error_events.append(e))

    scraper.scrape_job(job_id)

    assert error_events == []
    assert len(data_events) == 1
    assert data_events[0].job_id == job_id
    assert len(not_found_events) == 0


def test_scrape_single_job_not_found():
    scraper = LinkedinScraper(
        chrome_executable_path=None,
        chrome_options=None,
        chrome_user_data_dir=os.environ.get('LI_CHROME_USER_DATA_DIR'),
        headless=True,
        max_workers=1,
        slow_mo=0.8,
    )

    data_events = []
    not_found_events = []
    error_events = []

    scraper.on(Events.DATA, lambda d: data_events.append(d))
    scraper.on(Events.NOT_FOUND, lambda d: not_found_events.append(d))
    scraper.on(Events.ERROR, lambda e: error_events.append(e))

    scraper.scrape_job('9999999999999')

    assert len(data_events) == 0
    assert len(not_found_events) == 1
    assert not_found_events[0].job_id == '9999999999999'
    assert len(error_events) == 0
