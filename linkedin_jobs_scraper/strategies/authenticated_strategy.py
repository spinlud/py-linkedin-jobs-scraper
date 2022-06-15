import os
import traceback
import re
from typing import NamedTuple
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as ec
from time import sleep
from urllib.parse import urljoin
from .strategy import Strategy
from ..config import Config
from ..query import Query
from ..utils.logger import debug, info, warn, error
from ..utils.constants import HOME_URL
from ..utils.url import get_query_params, get_location, override_query_params
from ..utils.text import normalize_spaces
from ..events import Events, EventData
from ..exceptions import InvalidCookieException


class Selectors(NamedTuple):
    container = '.jobs-search-two-pane__results'
    chatPanel = '.msg-overlay-list-bubble'
    jobs = 'div.job-card-container'
    link = 'a.job-card-container__link'
    applyBtn = 'button.jobs-apply-button[role="link"]'
    title = '.artdeco-entity-lockup__title'
    company = '.artdeco-entity-lockup__subtitle'
    company_link = 'a.job-card-container__company-name'
    place = '.artdeco-entity-lockup__caption'
    date = 'time'
    description = '.jobs-description'
    detailsPanel = '.jobs-search__job-details--container'
    detailsTop = '.jobs-details-top-card'
    details = '.jobs-details__main-content'
    insights = '[class=jobs-unified-top-card__job-insight]'  # only one class
    pagination = '.jobs-search-two-pane__pagination'
    paginationNextBtn = 'li[data-test-pagination-page-btn].selected + li'  # not used
    paginationBtn = lambda index: f'li[data-test-pagination-page-btn="{index}"] button'  # not used


class AuthenticatedStrategy(Strategy):
    def __init__(self, scraper: 'LinkedinScraper'):
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
    def __load_jobs(driver: webdriver, job_tot: int, timeout=5) -> object:
        """
        Load more jobs
        :param driver: webdriver
        :param job_tot: int
        :param timeout: int
        :return: object
        """

        elapsed = 0
        sleep_time = 0.05

        try:
            while elapsed < timeout:
                jobs_count = driver.execute_script(
                        'return document.querySelectorAll(arguments[0]).length;', Selectors.jobs)

                if jobs_count > job_tot:
                    return {'success': True, 'count': jobs_count}

                sleep(sleep_time)
                elapsed += sleep_time
        except:
            pass

        return {'success': False, 'count': -1}

    @staticmethod
    def __load_job_details(driver: webdriver, job_id: str, timeout=5) -> object:
        """
        Wait for job details to load
        :param driver: webdriver
        :param job_id: str
        :param timeout: int
        :return: object
        """

        elapsed = 0
        sleep_time = 0.05

        try:
            while elapsed < timeout:
                loaded = driver.execute_script(
                    '''
                        const detailsPanel = document.querySelector(arguments[1]);
                        const description = document.querySelector(arguments[2]);
                        return detailsPanel && detailsPanel.innerHTML.includes(arguments[0]) &&
                            description && description.innerText.length > 0;
                    ''',
                    job_id,
                    Selectors.detailsPanel,
                    Selectors.description)

                if loaded:
                    return {'success': True}

                sleep(sleep_time)
                elapsed += sleep_time
        finally:
            pass

        return {'success': False, 'error': 'Timeout on loading job details'}

    @staticmethod
    def __paginate(driver: webdriver, current_url: str, tag: str, offset: int, timeout=5) -> object:
        try:
            url = override_query_params(current_url, {'start': offset})
            info(tag, f'Opening {url}')
            driver.get(url)

            elapsed = 0
            sleep_time = 0.05  # 50 ms

            info(tag, f'Waiting for new jobs to load')
            # Wait for new jobs to load
            while elapsed < timeout:
                loaded = driver.execute_script(
                    '''
                        return document.querySelectorAll(arguments[0]).length > 0;                
                    ''',
                    Selectors.jobs)

                if loaded:
                    return {'success': True}

                sleep(sleep_time)
                elapsed += sleep_time
        finally:
            pass

        return {'success': False, 'error': 'Timeout on pagination'}

    @staticmethod
    def __accept_cookies(driver: webdriver, tag: str) -> None:
        """
        Accept cookies
        :param driver:
        :param tag:
        :return:
        """

        try:
            driver.execute_script(
                '''
                    const buttons = Array.from(document.querySelectorAll('button'));
                    const cookieButton = buttons.find(e => e.innerText.includes('Accept cookies'));

                    if (cookieButton) {
                        cookieButton.click();
                    }
                '''
            )
        except:
            debug(tag, 'Failed to accept cookies')

    @staticmethod
    def __close_chat_panel(driver: webdriver, tag: str) -> None:
        """
        Close chat panel
        :param driver:
        :param tag:
        :return:
        """

        try:
            driver.execute_script(
                '''
                    const div = document.querySelector(arguments[0]);
                    if (div) {
                        div.style.display = "none";
                    }                
                ''',
                Selectors.chatPanel)
        except:
            debug(tag, 'Failed to close chat panel')

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
        """
        Run strategy
        :param driver: webdriver
        :param search_url: str
        :param query: Query
        :param location: str
        :param apply_link: bool
        :param page_load_timeout: int
        :param apply_page_load_timeout: int
        :return: None
        """

        tag = f'[{query.query}][{location}]'
        processed = 0
        skipped = 0
        pagination_index = 0
        pagination_size = 25

        # Open main page first to verify/set the session
        debug(tag, f'Opening {HOME_URL}')
        driver.get(HOME_URL)
        sleep(self.scraper.slow_mo)

        if not AuthenticatedStrategy.__is_authenticated_session(driver):
            info(tag, 'Setting authentication cookie')

            try:
                driver.add_cookie({
                    'name': 'li_at',
                    'value': Config.LI_AT_COOKIE,
                    'domain': '.www.linkedin.com'
                })
            except BaseException as e:
                error(tag, e)
                error(tag, traceback.format_exc())
                return

        # Open search url
        info(tag, f'Opening {search_url}')
        driver.get(search_url)
        sleep(self.scraper.slow_mo)

        # Verify session
        if not AuthenticatedStrategy.__is_authenticated_session(driver):
            message = 'The provided session cookie is invalid. ' \
                      'Check the documentation on how to obtain a valid session cookie.'
            raise InvalidCookieException(message)

        # Wait container
        try:
            WebDriverWait(driver, 5).until(ec.presence_of_element_located((By.CSS_SELECTOR, Selectors.container)))
        except BaseException as e:
            warn(tag, 'No jobs found, skip')
            return

        # Pagination loop
        while processed < query.options.limit:
            # Verify session in loop
            if not AuthenticatedStrategy.__is_authenticated_session(driver):
                warn(tag, 'Session is no longer valid, this may cause the scraper to fail')
                self.scraper.emit(Events.INVALID_SESSION)
            else:
                info(tag, 'Session is valid')

            AuthenticatedStrategy.__accept_cookies(driver, tag)
            AuthenticatedStrategy.__close_chat_panel(driver, tag)

            job_index = 0

            job_tot = driver.execute_script('return document.querySelectorAll(arguments[0]).length;', Selectors.jobs)

            if job_tot == 0:
                info(tag, 'No jobs found, skip')
                break

            info(tag, f'Found {job_tot} jobs')

            # Jobs loop
            while job_index < job_tot and processed < query.options.limit:
                sleep(self.scraper.slow_mo)
                tag = f'[{query.query}][{location}][{pagination_index * pagination_size + job_index + 1}]'

                try:
                    # Extract job main fields
                    debug(tag, 'Evaluating selectors', [
                        Selectors.jobs,
                        Selectors.link,
                        Selectors.company,
                        Selectors.place,
                        Selectors.date])

                    job_id, job_link, job_title, job_company, job_company_link, \
                    job_company_img_link, job_place, job_date = \
                        driver.execute_script(
                            '''
                                const index = arguments[0];
                                const job = document.querySelectorAll(arguments[1])[index];
                                const link = job.querySelector(arguments[2]);
                                
                                // Click job link and scroll
                                link.scrollIntoView();
                                link.click();
                                const linkUrl = link.getAttribute("href");
                            
                                const jobId = job.getAttribute("data-job-id");
                    
                                const title = job.querySelector(arguments[3]) ?
                                    job.querySelector(arguments[3]).innerText : "";
                                    
                                let company = "";
                                let companyLink = "";
                                const companyElem = job.querySelector(arguments[4]); 
                                
                                if (companyElem) {                                    
                                    company = companyElem.innerText;
                                    const protocol = window.location.protocol + '//';
                                    const host = window.location.host;
                                    companyLink = `${protocol}${host}${companyElem.getAttribute('href')}`;
                                }
                                
                                const companyImgLink = job.querySelector("img") ? 
                                    job.querySelector("img").getAttribute("src") : "";                                                            
    
                                const place = job.querySelector(arguments[5]) ?
                                    job.querySelector(arguments[5]).innerText : "";
    
                                const date = job.querySelector(arguments[6]) ?
                                    job.querySelector(arguments[6]).getAttribute('datetime') : "";
    
                                return [
                                    jobId,
                                    linkUrl,
                                    title,
                                    company,
                                    companyLink,
                                    companyImgLink,
                                    place,
                                    date,
                                ];                                                    
                            ''',
                            job_index,
                            Selectors.jobs,
                            Selectors.link,
                            Selectors.title,
                            Selectors.company_link,
                            Selectors.place,
                            Selectors.date)

                    job_title = normalize_spaces(job_title)
                    job_company = normalize_spaces(job_company)
                    job_place = normalize_spaces(job_place)

                    # Join with base location if link is relative
                    job_link = urljoin(get_location(driver.current_url), job_link)

                    sleep(self.scraper.slow_mo)

                    # Wait for job details to load
                    debug(tag, f'Loading details job {job_id}')
                    load_result = AuthenticatedStrategy.__load_job_details(driver, job_id)

                    if not load_result['success']:
                        error(tag, load_result['error'], exc_info=False)
                        info(tag, 'Skipped')
                        job_index += 1
                        skipped += 1
                        continue

                    # Extract
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

                    # Extract insights
                    debug(tag, 'Evaluating selectors', [Selectors.insights])

                    job_insights = driver.execute_script(
                        r'''
                            const nodes = document.querySelectorAll(arguments[0]);
                            return Array.from(nodes).map(e => e.textContent.replace(/[\n\r\t ]+/g, ' ').trim());                            
                        ''',
                        Selectors.insights)

                    # Apply link
                    job_apply_link = ''

                    if apply_link:
                        try:
                            debug(tag, 'Evaluating selectors', [Selectors.applyBtn])

                            if driver.execute_script(
                                r'''
                                    const applyBtn = document.querySelector(arguments[0]);

                                    if (applyBtn) {
                                        applyBtn.click();
                                        return true;
                                    }

                                    return false;
                                ''',
                                Selectors.applyBtn
                            ) and len(driver.window_handles) > 1:
                                debug(tag, 'Try extracting apply link')

                                try:
                                    # Trick to avoid wasting time loading apply page.
                                    # It seems `driver.current_url` blocks until page is loaded, so we force a timeout
                                    # and set `job_apply_link` in the except block. This doesn't work always: sometimes
                                    # we get `about:blank` instead of the correct url.
                                    driver.switch_to.window(driver.window_handles[-1])  # Switch to apply page
                                    driver.set_page_load_timeout(apply_page_load_timeout)
                                    job_apply_link = driver.current_url
                                except:
                                    job_apply_link = driver.current_url if driver.current_url != 'about:blank' else ''
                        except BaseException as e:
                            warn(tag, 'Failed to extract apply link', e)
                        finally:
                            driver.set_page_load_timeout(page_load_timeout)

                            if len(driver.window_handles) > 1:
                                driver.switch_to.window(driver.window_handles[-1])
                                driver.close()
                                driver.switch_to.window(driver.window_handles[0])

                    data = EventData(
                        query=query.query,
                        location=location,
                        job_id=job_id,
                        job_index=job_index,
                        title=job_title,
                        company=job_company,
                        company_link=job_company_link,
                        company_img_link=job_company_img_link,
                        place=job_place,
                        date=job_date,
                        link=job_link,
                        apply_link=job_apply_link,
                        description=job_description,
                        description_html=job_description_html,
                        insights=job_insights)

                    info(tag, 'Processed')

                    job_index += 1
                    processed += 1

                    self.scraper.emit(Events.DATA, data)

                    # Try fetching more jobs
                    if processed < query.options.limit and job_index == job_tot < pagination_size:
                        load_jobs_result = AuthenticatedStrategy.__load_jobs(driver, job_tot)

                        if load_jobs_result['success']:
                            job_tot = load_jobs_result['count']

                    if job_index == job_tot:
                        break

                except BaseException as e:
                    try:
                        # Verify session on error
                        if not AuthenticatedStrategy.__is_authenticated_session(driver):
                            warn(tag, 'Session is no longer valid, this may cause the scraper to fail')
                            self.scraper.emit(Events.INVALID_SESSION)

                        error(tag, e, traceback.format_exc())
                        self.scraper.emit(Events.ERROR, str(e) + '\n' + traceback.format_exc())
                    finally:
                        info(tag, 'Skipped')
                        job_index += 1
                        skipped += 1

                    continue

            tag = f'[{query.query}][{location}]'

            info(tag, 'No more jobs to process in this page')

            # Print results so far
            info(tag, 'Processed:', processed)
            info(tag, 'Skipped:', skipped)
            info(tag, 'Missed:', (pagination_index + 1) * pagination_size - processed - skipped)

            # Check if we reached the limit of jobs to process
            if processed == query.options.limit:
                info(tag, 'Query limit reached!')
                break

            # Try to paginate
            pagination_index += 1
            info(tag, f'Pagination requested [{pagination_index}]')
            offset = pagination_index * pagination_size
            paginate_result = AuthenticatedStrategy.__paginate(driver, search_url, tag, offset)

            if not paginate_result['success']:
                info(tag, "Couldn't find more jobs for the running query")
                return
