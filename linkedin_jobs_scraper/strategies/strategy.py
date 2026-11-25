from typing import TYPE_CHECKING

from selenium.webdriver.remote.webdriver import WebDriver

from ..query import Query
from ..utils.location_picker import PickedLocation

if TYPE_CHECKING:
    from ..linkedin_scraper import LinkedinScraper


class Strategy:
    def __init__(self, scraper: 'LinkedinScraper'):
        self.scraper = scraper

    def run(
        self,
        driver: WebDriver,
        search_url: str,
        query: Query,
        location: str,
        page_offset: int,
        expected_location: str = '',
    ) -> None:
        raise NotImplementedError('Must implement method in subclass')

    def resolve_location(self, driver: WebDriver, tag: str, name: str) -> PickedLocation | None:
        raise NotImplementedError('Must implement method in subclass')

    def scrape_job(self, driver: WebDriver, job_id: str, apply_link: bool = False) -> None:
        raise NotImplementedError('Must implement method in subclass')
