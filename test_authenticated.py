import os
import logging
from selenium.webdriver.chrome.options import Options
from linkedin_jobs_scraper import \
    LinkedinScraper, \
    Query, \
    QueryOptions, \
    QueryFilters, \
    Events, \
    Data, \
    ETimeFilterOptions


def test_authenticated_strategy():
    # Check env
    if 'LI_AT_COOKIE' not in os.environ or len(os.environ['LI_AT_COOKIE']) < 1:
        raise RuntimeError('Env variable LI_AT_COOKIE must be set')

    scraper = LinkedinScraper(
        chrome_options=None,
        max_workers=1,
        slow_mo=0.9,
    )

    def __on_data(data: Data):
        assert isinstance(data.query, str)
        assert isinstance(data.location, str)
        assert isinstance(data.link, str)
        assert isinstance(data.apply_link, str)
        assert isinstance(data.title, str)
        assert isinstance(data.company, str)
        assert isinstance(data.place, str)
        assert isinstance(data.description, str)
        assert isinstance(data.description_html, str)
        assert isinstance(data.date, str)
        assert isinstance(data.seniority_level, str)
        assert isinstance(data.job_function, str)
        assert isinstance(data.employment_type, str)
        assert isinstance(data.industries, str)

    def __on_error(error):
        print('[ON_ERROR]', error)

    def __on_end():
        print('[ON_END]')

    scraper.on(Events.DATA.value, __on_data)
    scraper.on(Events.ERROR.value, __on_error)
    scraper.on(Events.END.value, __on_end)

    queries = [
        Query(query='Software Engineer', options=QueryOptions(locations=['Germany'], optimize=False, limit=5))
    ]

    scraper.run(queries)


# test_authenticated_strategy()
