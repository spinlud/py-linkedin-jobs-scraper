import traceback
from typing import NamedTuple
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as ec
from .RunStrategy import RunStrategy
from ..query import Query
from ..utils.logger import debug, info, warn, error
from ..events import Events, Data
from time import sleep


class Selectors(NamedTuple):
    container = '.results__container.results__container--two-pane'
    links = '.jobs-search__results-list li a.result-card__full-card-link'
    applyLink = 'a[data-is-offsite-apply=true]'
    dates = 'time'
    companies = '.result-card__subtitle.job-result-card__subtitle'
    places = '.job-result-card__location'
    detailsTop = '.topcard__content-left'
    description = '.description__text'
    criteria = 'li.job-criteria__item'
    seeMoreJobs = 'button.infinite-scroller__show-more-button'


class LoggedOutRunStrategy(RunStrategy):
    from linkedin_jobs_scraper import LinkedinScraper

    def __init__(self, scraper: LinkedinScraper):
        super().__init__(scraper)

    def run(self, driver: webdriver, search_url: str, query: Query, location: str) -> None:
        tag = f'[{query.query}][{location}]'
        processed = 0

        info(tag, f'Opening {search_url}')
        driver.get(search_url)

        # Wait
        try:
            WebDriverWait(driver, 5).until(ec.presence_of_element_located((By.CSS_SELECTOR, Selectors.container)))
        except BaseException as e:
            info(tag, 'No jobs found, skip')
            return

        # Pagination loop
        while processed < query.options.limit:
            job_index = 0

            job_links_tot = driver.execute_script('return document.querySelectorAll(arguments[0]).length;',
                                                  Selectors.links)

            if job_links_tot == 0:
                info(tag, 'No jobs found, skip')
                break

            info(tag, f'Found {job_links_tot} jobs')

            # Jobs loop
            while job_index < job_links_tot and processed < query.options.limit:
                tag = f'[{query.query}][{location}][{processed + 1}]'

                job_link = None
                job_apply_link = None
                job_title = None
                job_company = None
                job_place = None
                job_description = None
                job_description_html = None
                job_date = None
                job_senority_level = None
                job_function = None
                job_employment_type = None
                job_industries = None
                load_job_details_result = None

                # Extract job main fields
                debug(tag, 'Evaluating selectors', [
                    Selectors.links,
                    Selectors.companies,
                    Selectors.places,
                    Selectors.dates])

                try:
                    job_title, job_company, job_place, job_date = driver.execute_script('''
                        return [
                            document.querySelectorAll(arguments[1])[arguments[0]].innerText,
                            document.querySelectorAll(arguments[2])[arguments[0]].innerText,
                            document.querySelectorAll(arguments[3])[arguments[0]].innerText,
                            document.querySelectorAll(arguments[4])[arguments[0]].innerText
                        ];
                    ''', job_index, Selectors.links, Selectors.companies, Selectors.places, Selectors.dates)

                    # Load job details and extract job link
                    debug(tag, 'Evaluating selectors', [
                        Selectors.links])

                    job_link = driver.execute_script('''
                        const linkElem = document.querySelectorAll(arguments[1])[arguments[0]];
                        linkElem.scrollIntoView();
                        linkElem.click();
                        return linkElem.getAttribute("href");
                    ''', job_index, Selectors.links)

                except BaseException as e:
                    error(tag, e, traceback.format_exc())
                    self.scraper.emit(Events.ERROR.value, str(e))
                    job_index += 1
                    continue

                data = Data(
                    query=query.query,
                    location=location,
                    title=job_title,
                    company=job_company,
                    place=job_place,
                    date=job_date,
                    link=job_link)

                info(tag, 'Processed')

                job_index += 1
                processed += 1

                self.scraper.emit(Events.DATA.value, data)

                sleep(1)

            break  # REMOVE




