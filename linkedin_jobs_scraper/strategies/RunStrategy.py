from ..query import Query
from selenium import webdriver


class RunStrategy:
    from linkedin_jobs_scraper import LinkedinScraper

    def __init__(self, scraper: LinkedinScraper):
        self.scraper = scraper

    def run(self, driver: webdriver, search_url: str, query: Query, location: str) -> None:
        raise NotImplementedError('Need to implement method in subclass')
