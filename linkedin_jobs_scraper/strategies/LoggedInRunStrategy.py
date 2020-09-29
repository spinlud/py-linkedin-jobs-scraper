from typing import NamedTuple
from .RunStrategy import RunStrategy
from ..query import Query
from selenium import webdriver


class Selectors(NamedTuple):
    container = '.jobs-search-two-pane__container'
    toggleChatBtn = '.msg-overlay-bubble-header__controls button:nth-of-type(2)'
    links = 'a.job-card-container__link.job-card-list__title'
    companies = 'div[data-test-job-card-list__company-name]'
    places = 'li[data-test-job-card-list__location]'
    dates = 'time[data-test-job-card-container__listed-time=true]'
    description = '.jobs-description'
    detailsTop = '.jobs-details-top-card'
    details = '.jobs-details__main-content'
    criteria = '.jobs-box__group h3'
    pagination = '.jobs-search-two-pane__pagination'
    paginationBtn = lambda index: f'li[data-test-pagination-page-btn="{index}"] button'


class LoggedInRunStrategy(RunStrategy):
    from linkedin_jobs_scraper import LinkedinScraper

    def __init__(self, scraper: LinkedinScraper):
        super().__init__(scraper)

    def run(self, driver: webdriver, search_url: str, query: Query, location: str) -> None:
        return
