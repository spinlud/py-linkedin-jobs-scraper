#!/usr/bin/env python

import os
import logging
import pytest
from .shared import on_begin, on_data, on_single_job_data, on_error, on_invalid_session, on_end
from linkedin_jobs_scraper import LinkedinScraper
from linkedin_jobs_scraper.events import Events, EventData
from linkedin_jobs_scraper.query import Query, QueryOptions, QueryFilters
from linkedin_jobs_scraper.filters import RelevanceFilters, TimeFilters, TypeFilters, ExperienceLevelFilters, OnSiteOrRemoteFilters

def _has_credentials() -> bool:
    if os.environ.get('LI_CHROME_USER_DATA_DIR'):
        return True
    if os.environ.get('LI_RM_COOKIE') and os.environ.get('LI_BCOOKIE'):
        return True
    return bool(os.environ.get('LI_AT_COOKIE'))


pytestmark = pytest.mark.skipif(
    not _has_credentials(),
    reason='no LinkedIn credentials in the environment (LI_RM_COOKIE + LI_BCOOKIE, LI_AT_COOKIE, or LI_CHROME_USER_DATA_DIR)')


# Job ids captured live from the search run, so the single-job test can target a
# currently-live posting rather than a hardcoded id LinkedIn may have removed.
captured_job_ids = []


def _capture_job_id(data):
    captured_job_ids.append(data.job_id)


def test_run():
    # Change other logger levels
    logging.getLogger('urllib3').setLevel(logging.WARN)
    logging.getLogger('selenium').setLevel(logging.WARN)

    scraper = LinkedinScraper(
        chrome_executable_path=None,
        chrome_options=None,
        chrome_user_data_dir=os.environ.get('LI_CHROME_USER_DATA_DIR'),
        headless=True,
        max_workers=1,
        slow_mo=0.8,
    )

    scraper.on(Events.BEGIN, on_begin)
    scraper.on(Events.DATA, on_data)
    scraper.on(Events.DATA, _capture_job_id)
    scraper.on(Events.ERROR, on_error)
    scraper.on(Events.INVALID_SESSION, on_invalid_session)
    scraper.on(Events.END, on_end)

    queries = [
        Query(
            options=QueryOptions(
                filters=QueryFilters(
                    company_jobs_url='https://www.linkedin.com/jobs/search/?f_C=1441%2C17876832%2C791962%2C2374003%2C18950635%2C16140%2C10440912&geoId=92000000',
                    time=TimeFilters.MONTH,
                    type=[TypeFilters.FULL_TIME, TypeFilters.INTERNSHIP, TypeFilters.CONTRACT],
                )
            )
        ),

        Query(
            query='Software Engineer',
            options=QueryOptions(
                locations=['United States'],
                apply_link=True,
                limit=27,
                filters=QueryFilters(
                    time=TimeFilters.WEEK,
                    experience=ExperienceLevelFilters.MID_SENIOR,
                    on_site_or_remote=[OnSiteOrRemoteFilters.ON_SITE]
                )
            )
        ),

        # Query(
        #     query='Analyst',
        #     options=QueryOptions(
        #         locations=['Germany'],
        #         skip_promoted_jobs=True,
        #         limit=3,
        #         filters=QueryFilters(
        #             time=TimeFilters.MONTH,
        #             relevance=RelevanceFilters.RELEVANT,
        #         )
        #     )
        # ),
    ]

    scraper.run(
        queries=queries,
        # Global options
        options=QueryOptions(
            locations=['United Kingdom'],
            limit=10,
        )
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

    scraper.on(Events.DATA, on_single_job_data)
    scraper.on(Events.DATA, lambda d: data_events.append(d))
    scraper.on(Events.NOT_FOUND, lambda d: not_found_events.append(d))
    scraper.on(Events.ERROR, on_error)

    scraper.scrape_job(job_id)

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
