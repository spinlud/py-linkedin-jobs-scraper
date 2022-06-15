from selenium import webdriver
from ..query import Query


class Strategy:
    def __init__(self, scraper: 'LinkedinScraper'):
        self.scraper = scraper

    def run(
        self,
        driver: webdriver,
        search_url: str,
        query: Query,
        location: str,
        apply_link: bool,
        page_load_timeout: int,
        apply_page_load_timeout: int
    ) -> None:
        raise NotImplementedError('Must implement method in subclass')
