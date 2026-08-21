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
        page_offset: int
    ) -> None:
        raise NotImplementedError('Must implement method in subclass')

    def scrape_job(
        self,
        driver: webdriver,
        job_id: str,
        apply_link: bool = False
    ) -> None:
        raise NotImplementedError('Must implement method in subclass')
