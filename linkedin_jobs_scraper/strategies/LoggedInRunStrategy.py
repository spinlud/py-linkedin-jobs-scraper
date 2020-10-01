import os
import traceback
from typing import NamedTuple
from .RunStrategy import RunStrategy
from ..query import Query
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as ec
from ..query import Query
from ..utils.logger import debug, info, warn, error
from ..events import Events, Data
from time import sleep


class Selectors(NamedTuple):
    container = '.jobs-search-two-pane__container'
    toggleChatBtn = '.msg-overlay-bubble-header__controls button:nth-of-type(2)'
    chatPanel = '.msg-overlay-list-bubble'
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

    @staticmethod
    def __is_authenticated_session(driver: webdriver):
        """
        Return True if authenticated session cookie is set, False otherwise
        :param driver: webdriver
        :return:
        """
        return driver.get_cookie('li_at') is not None

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
            loaded = driver.execute_script('''
                    const description = document.querySelector(arguments[0]);
                    return description && description.innerText.length > 0;    
                ''', Selectors.description)

            if loaded:
                return {'success': True}

            sleep(sleep_time)
            elapsed += sleep_time

        return {'success': False, 'error': 'Timeout on loading job details'}

    @staticmethod
    def __paginate(driver: webdriver, pagination_index: int, timeout=2) -> object:
        """
        Attempt to paginate
        :param driver: webdriver
        :param pagination_index: int
        :return: object
        """

        elapsed = 0
        sleep_time = 0.05
        clicked = False
        pagination_btn_selector = Selectors.paginationBtn(pagination_index)

        try:
            WebDriverWait(driver, 5).until(ec.presence_of_element_located((By.CSS_SELECTOR, Selectors.pagination)))
        except:
            return {'success': False, 'error': 'Timeout on pagination'}

        while elapsed < timeout:
            if not clicked:
                clicked = driver.execute_script('''
                    const btn = document.querySelector(arguments[0]);
                    
                    if (btn) {
                        btn.click();
                        return true;
                    }
                    else {
                        return false;
                    }
                ''', pagination_btn_selector)

            loaded = driver.execute_script('''
                return document.querySelectorAll(arguments[0]).length > 0;                
            ''', Selectors.links)

            if loaded:
                return {'success': True}

            sleep(sleep_time)
            elapsed += sleep_time

        return {'success': False, 'error': 'Timeout on pagination'}

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
        pagination_index = 1

        # Open url
        info(tag, f'Opening {search_url}')
        driver.get(search_url)
        sleep(1)

        # Set cookie if not authenticated
        if not LoggedInRunStrategy.__is_authenticated_session(driver):
            info(tag, 'Setting authentication cookie')

            try:
                driver.add_cookie({
                    'name': 'li_at',
                    'value': os.environ['LI_AT_COOKIE'],
                    'domain': '.www.linkedin.com'
                })

                # Fetch url again after setting the cookie
                driver.get(search_url)
            except BaseException as e:
                error(tag, e)
                error(tag, traceback.format_exc())
                return

        # Verify session
        if not LoggedInRunStrategy.__is_authenticated_session(driver):
            error(tag, 'The provided session cookie is invalid. Check the documentation on how to obtain a valid session cookie.')
            return

        # Wait container
        try:
            WebDriverWait(driver, 5).until(ec.presence_of_element_located((By.CSS_SELECTOR, Selectors.container)))
        except BaseException as e:
            info(tag, 'No jobs found, skip')
            return

        # Try closing chat panel
        try:
            driver.execute_script('''
                const div = document.querySelector(arguments[0]);
                if (div) {
                    div.style.display = "none";
                }                
            ''', Selectors.chatPanel)
        except:
            pass

        # Pagination loop
        while processed < query.options.limit:
            # Verify session in loop
            if not LoggedInRunStrategy.__is_authenticated_session(driver):
                warn(tag, 'Session is invalid, this may cause the scraper to fail')
            else:
                info(tag, 'Session is valid')

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
                    job_title, job_company, job_place, job_date = driver.execute_script('''
                        return [
                            document.querySelectorAll(arguments[1])[arguments[0]].innerText,
                            document.querySelectorAll(arguments[2])[arguments[0]].innerText,
                            document.querySelectorAll(arguments[3])[arguments[0]].innerText,
                            document.querySelectorAll(arguments[4])[arguments[0]].getAttribute('datetime')
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

                    # Wait for job details to load
                    load_result = LoggedInRunStrategy.__load_job_details(driver)

                    if not load_result['success']:
                        error(tag, load_result['error'])
                        job_index += 1
                        continue

                    # Exctract
                    debug(tag, 'Evaluating selectors', [Selectors.description])

                    job_description, job_description_html = driver.execute_script('''
                                        const el = document.querySelector(arguments[0]);

                                        return [
                                            el.innerText,
                                            el.outerHTML    
                                        ];
                                    ''', Selectors.description)

                    # TODO how to extract apply link?

                    # Extract criteria
                    debug(tag, 'Evaluating selectors', [Selectors.criteria])

                    job_seniority_level, job_function, job_employment_type, job_industries = driver.execute_script(r'''
                        const nodes = document.querySelectorAll(arguments[0]);

                        const criteria = [
                            "Seniority Level",
                            "Employment Type",
                            "Industry",
                            "Job Functions",
                        ];

                        return Array.from(criteria.map(c => {
                            const el = Array.from(nodes).find(node => node.innerText.trim() === c);
                        
                            if (el && el.nextElementSibling) {
                                const sibling = el.nextElementSibling;
                                return sibling.innerText
                                    .replace(/[\s]{2,}/g, ", ")
                                    .replace(/[\n\r]+/g, " ")
                                    .trim();
                            }
                            else {
                                return "";
                            }
                        }));
                    ''', Selectors.criteria)

                except BaseException as e:
                    error(tag, e, traceback.format_exc())
                    self.scraper.emit(Events.ERROR.value, str(e) + '\n' + traceback.format_exc())
                    job_index += 1
                    continue

                data = Data(
                    query=query.query,
                    location=location,
                    title=job_title,
                    company=job_company,
                    place=job_place,
                    date=job_date,
                    link=job_link,
                    apply_link='',
                    description=job_description,
                    description_html=job_description_html,
                    seniority_level=job_seniority_level,
                    job_function=job_function,
                    employment_type=job_employment_type,
                    industries=job_industries)

                info(tag, 'Processed')

                job_index += 1
                processed += 1

                self.scraper.emit(Events.DATA.value, data)

                # Try fetching more jobs
                if processed < query.options.limit and job_index == job_links_tot:
                    job_links_tot = driver.execute_script('return document.querySelectorAll(arguments[0]).length;',
                                                          Selectors.links)

            # Check if we reached the limit of jobs to process
            if processed == query.options.limit:
                break

            # Try to paginate
            pagination_index += 1
            info(tag, f'Pagination requested ({pagination_index})')
            paginate_result = LoggedInRunStrategy.__paginate(driver, pagination_index)

            if not paginate_result['success']:
                info(tag, "Couldn't find more jobs for the running query")
                return
