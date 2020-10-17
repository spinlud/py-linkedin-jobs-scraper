import traceback
from typing import NamedTuple
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as ec
from urllib.parse import urlparse
from time import sleep
from .strategy import Strategy
from ..query import Query
from ..utils.logger import debug, info, warn, error
from ..events import Events, EventData


class Selectors(NamedTuple):
    container = '.results__container.results__container--two-pane'
    jobs = '.jobs-search__results-list li'
    links = '.jobs-search__results-list li a.result-card__full-card-link'
    applyLink = 'a[data-is-offsite-apply=true]'
    dates = 'time'
    companies = '.result-card__subtitle.job-result-card__subtitle'
    places = '.job-result-card__location'
    detailsTop = '.topcard__content-left'
    description = '.description__text'
    criteria = 'li.job-criteria__item'
    seeMoreJobs = 'button.infinite-scroller__show-more-button'


class AnonymousStrategy(Strategy):
    def __init__(self, scraper: 'LinkedinScraper'):
        super().__init__(scraper)

    @staticmethod
    def __require_authentication(driver: webdriver) -> bool:
        """
        Verify if driver has been redirected to auth wall and needs authentication
        :param driver: webdriver
        :return: bool
        """

        parsed = urlparse(driver.current_url)
        return 'authwall' in parsed.path.lower()

    @staticmethod
    def __load_job_details(driver: webdriver, timeout=2) -> object:
        """
        Wait for job details to load
        :param driver: webdriver
        :param timeout: int
        :return: object
        """
        elapsed = 0
        sleep_time = 0.05

        while elapsed < timeout:
            loaded = driver.execute_script(
                '''
                    const description = document.querySelector(arguments[0]);
                    return description && description.innerText.length > 0;    
                ''',
                Selectors.description)

            if loaded:
                return {'success': True}

            sleep(sleep_time)
            elapsed += sleep_time

        return {'success': False, 'error': 'Timeout on loading job details'}

    @staticmethod
    def __load_more_jobs(driver: webdriver, job_links_tot: int, timeout=2) -> object:
        """

        :param driver:
        :param job_links_tot:
        :param timeout:
        :return:
        """

        elapsed = 0
        sleep_time = 0.05
        clicked = False

        while elapsed < timeout:
            if not clicked:
                clicked = driver.execute_script(
                    '''
                        const button = document.querySelector(arguments[0]);
    
                        if (button) {
                            button.click();
                            return true;
                        }
                        else {
                            return false;
                        }    
                    ''',
                    Selectors.seeMoreJobs)

            loaded = driver.execute_script(
                '''
                    window.scrollTo(0, document.body.scrollHeight);
                    return document.querySelectorAll(arguments[0]).length > arguments[1];
                ''',
                Selectors.links,
                job_links_tot)

            if loaded:
                return {'success': True}

            sleep(sleep_time)
            elapsed += sleep_time

        return {'success': False, 'error': 'Timeout on loading more jobs'}

    def run(self, driver: webdriver, search_url: str, query: Query, location: str) -> None:
        """
        Run scraper
        :param driver: webdriver
        :param search_url: str
        :param query: Query
        :param location: str
        :return: None
        """

        tag = f'[{query.query}][{location}]'
        processed = 0

        info(tag, f'Opening {search_url}')
        driver.get(search_url)

        # Verify if redirected to auth wall
        if AnonymousStrategy.__require_authentication(driver):
            error('Scraper failed to run in anonymous mode, authentication may be necessary for this environment. '
                  'Please check the documentation on how to use an authenticated session.')
            return

        # Wait container
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
                sleep(self.scraper.slow_mo)
                tag = f'[{query.query}][{location}][{processed + 1}]'

                # Extract job main fields
                debug(tag, 'Evaluating selectors', [
                    Selectors.links,
                    Selectors.companies,
                    Selectors.places,
                    Selectors.dates])

                try:
                    job_id, job_title, job_company, job_place, job_date = driver.execute_script(
                        '''
                            return [
                                document.querySelectorAll(arguments[1])[arguments[0]].getAttribute('data-id'),
                                document.querySelectorAll(arguments[2])[arguments[0]].innerText,
                                document.querySelectorAll(arguments[3])[arguments[0]].innerText,
                                document.querySelectorAll(arguments[4])[arguments[0]].innerText,
                                document.querySelectorAll(arguments[5])[arguments[0]].getAttribute('datetime')
                            ];
                        ''',
                        job_index,
                        Selectors.jobs,
                        Selectors.links,
                        Selectors.companies,
                        Selectors.places,
                        Selectors.dates)

                    # Load job details and extract job link
                    debug(tag, 'Evaluating selectors', [
                        Selectors.links])

                    job_link = driver.execute_script(
                        '''
                            const linkElem = document.querySelectorAll(arguments[1])[arguments[0]];
                            linkElem.scrollIntoView();
                            linkElem.click();
                            return linkElem.getAttribute("href");
                        ''',
                        job_index,
                        Selectors.links)

                    # Wait for job details to load
                    load_result = AnonymousStrategy.__load_job_details(driver)

                    if not load_result['success']:
                        error(tag, load_result['error'])
                        job_index += 1
                        continue

                    # Exctract
                    debug(tag, 'Evaluating selectors', [Selectors.description])

                    job_description, job_description_html = driver.execute_script(
                        '''
                            const el = document.querySelector(arguments[0]);
                        
                            return [
                                el.innerText,
                                el.outerHTML    
                            ];
                        ''',
                        Selectors.description)

                    # Extract apply link
                    debug(tag, 'Evaluating selectors', [Selectors.applyLink])

                    job_apply_link = driver.execute_script(
                        '''
                            const applyBtn = document.querySelector(arguments[0]);
                            return applyBtn ? applyBtn.getAttribute("href") : '';
                        ''',
                        Selectors.applyLink)

                    # Extract criteria
                    debug(tag, 'Evaluating selectors', [Selectors.criteria])

                    job_seniority_level, job_function, job_employment_type, job_industries = driver.execute_script(
                        '''
                            const items = document.querySelectorAll(arguments[0]);
    
                            const criteria = [
                                'Seniority level',
                                'Job function',
                                'Employment type',
                                'Industries'
                            ];
    
                            const nodeList = criteria.map(criteria => {
                                const el = Array.from(items)
                                    .find(li =>
                                        (li.querySelector('h3')).innerText === criteria);
    
                                return el ? el.querySelectorAll('span') : [];
                            });
    
                            return Array.from(nodeList)
                                .map(spanList => Array.from(spanList)
                                    .map(e => e.innerText).join(', '));
                        ''',
                        Selectors.criteria)

                except BaseException as e:
                    error(tag, e, traceback.format_exc())
                    self.scraper.emit(Events.ERROR, str(e) + '\n' + traceback.format_exc())
                    job_index += 1
                    continue

                data = EventData(
                    query=query.query,
                    location=location,
                    job_id=job_id,
                    title=job_title,
                    company=job_company,
                    place=job_place,
                    date=job_date,
                    link=job_link,
                    apply_link=job_apply_link,
                    description=job_description,
                    description_html=job_description_html,
                    seniority_level=job_seniority_level,
                    job_function=job_function,
                    employment_type=job_employment_type,
                    industries=job_industries)

                info(tag, 'Processed')

                job_index += 1
                processed += 1

                self.scraper.emit(Events.DATA, data)

                # Try fetching more jobs
                if processed < query.options.limit and job_index == job_links_tot:
                    job_links_tot = driver.execute_script('return document.querySelectorAll(arguments[0]).length;',
                                                          Selectors.links)

            # Check if we reached the limit of jobs to process
            if processed == query.options.limit:
                break

            # Check if we need to paginate
            info(tag, 'Checking for new jobs to load...')
            load_result = AnonymousStrategy.__load_more_jobs(driver, job_links_tot)

            if not load_result['success']:
                info(tag, "Couldn't find more jobs for the running query")
                break
