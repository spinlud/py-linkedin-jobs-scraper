#!/usr/bin/env python

import os
import logging
from .shared import on_data, on_error, on_invalid_session, on_end
from linkedin_jobs_scraper import LinkedinScraper
from linkedin_jobs_scraper.events import Events, EventData
from linkedin_jobs_scraper.query import Query, QueryOptions, QueryFilters
from linkedin_jobs_scraper.filters import RelevanceFilters, TimeFilters, TypeFilters, ExperienceLevelFilters, OnSiteOrRemoteFilters

def test_run():
    # Change other logger levels
    logging.getLogger('urllib3').setLevel(logging.WARN)
    logging.getLogger('selenium').setLevel(logging.WARN)

    scraper = LinkedinScraper(
        chrome_executable_path=None,
        chrome_options=None,
        headless=True,
        max_workers=1,
        slow_mo=0.65,
    )

    scraper.on(Events.DATA, on_data)
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
