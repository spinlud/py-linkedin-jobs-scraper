#!/usr/bin/env python

import os
import logging
from selenium.webdriver.chrome.options import Options
from .shared import on_data, on_error, on_invalid_session, on_end
from linkedin_jobs_scraper import LinkedinScraper
from linkedin_jobs_scraper.events import Events, EventData
from linkedin_jobs_scraper.query import Query, QueryOptions, QueryFilters
from linkedin_jobs_scraper.filters import RelevanceFilters, TimeFilters, TypeFilters, ExperienceLevelFilters


def test_run():
    # Change other logger levels
    logging.getLogger('urllib3').setLevel(logging.WARN)
    logging.getLogger('selenium').setLevel(logging.WARN)

    scraper = LinkedinScraper(
        chrome_executable_path=None,
        chrome_options=None,
        headless=True,
        max_workers=1,
        slow_mo=0.8,
    )

    scraper.on(Events.DATA, on_data)
    scraper.on(Events.ERROR, on_error)
    scraper.on(Events.INVALID_SESSION, on_invalid_session)
    scraper.on(Events.END, on_end)

    queries = [
        Query(),
        Query(
            query='Engineer',
            options=QueryOptions(
                locations=['United States'],
                optimize=False,
                limit=5,
                filters=QueryFilters(
                    company_jobs_url='https://www.linkedin.com/jobs/search/?f_C=1441%2C17876832%2C791962%2C2374003%2C18950635%2C16140%2C10440912&geoId=92000000',
                    time=TimeFilters.MONTH,
                    type=[TypeFilters.FULL_TIME, TypeFilters.INTERNSHIP]
                )
            )
        )
    ]

    scraper.run(
        queries=queries,
        # Global options
        options=QueryOptions(
            locations=['United Kingdom'],
            limit=10,
            optimize=False,
        )
    )
