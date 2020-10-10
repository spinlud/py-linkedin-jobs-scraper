#!/usr/bin/env python

import os
import logging
from selenium.webdriver.chrome.options import Options
from .shared import on_data, on_error, on_end
from linkedin_jobs_scraper import \
    LinkedinScraper, \
    Query, \
    QueryOptions, \
    QueryFilters, \
    Events, \
    TimeFilters, \
    TypeFilters, \
    ExperienceLevelFilters


def test_authenticated_strategy():
    # Check env
    if 'LI_AT_COOKIE' not in os.environ or len(os.environ['LI_AT_COOKIE']) < 1:
        raise RuntimeError('Env variable LI_AT_COOKIE must be set')

    scraper = LinkedinScraper(
        chrome_options=None,
        max_workers=1,
        slow_mo=0.4,
    )

    scraper.on(Events.DATA, on_data)
    scraper.on(Events.ERROR, on_error)
    scraper.on(Events.END, on_end)

    queries = [
        Query(
            options=QueryOptions(
                optimize=False,
                limit=27
            )
        ),
        Query(
            query='Designer',
            options=QueryOptions(
                locations=['Asia'],
                optimize=False,
                limit=5,
                filters=QueryFilters(
                    time=TimeFilters.MONTH,
                    type=[TypeFilters.FULL_TIME, TypeFilters.CONTRACT],
                    experience=[ExperienceLevelFilters.MID_SENIOR, ExperienceLevelFilters.ENTRY_LEVEL]
                )
            )
        ),

    ]

    scraper.run(queries)
