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


class Selectors:
    switch_selectors = False

    @property
    def container(self):
        return '.results__container.results__container--two-pane' if not Selectors.switch_selectors else \
            '.two-pane-serp-page__results-list'

    @property
    def jobs(self):
        return '.jobs-search__results-list li' if not Selectors.switch_selectors else \
            '.jobs-search__results-list li'

    @property
    def links(self):
        return '.jobs-search__results-list li a.result-card__full-card-link' if not Selectors.switch_selectors else \
            'a.base-card__full-link'

    @property
    def applyLink(self):
        return 'a[data-is-offsite-apply=true]'

    @property
    def dates(self):
        return 'time'

    @property
    def companies(self):
        return '.result-card__subtitle.job-result-card__subtitle' if not Selectors.switch_selectors else \
            '.base-search-card__subtitle'

    @property
    def places(self):
        return '.job-result-card__location' if not Selectors.switch_selectors else \
            '.job-search-card__location'

    @property
    def detailsPanel(self):
        return '.details-pane__content'

    @property
    def description(self):
        return '.description__text'

    @property
    def seeMoreJobs(self):
        return 'button.infinite-scroller__show-more-button'


class AnonymousStrategy(Strategy):
    def __init__(self, scraper: 'LinkedinScraper'):
        warn('AnonymousStrategy is no longer maintained and it won\'t probably work. It is recommended to use an authenticated session, see documentation at https://github.com/spinlud/py-linkedin-jobs-scraper#anonymous-vs-authenticated-session.')
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
    def __load_job_details(driver: webdriver, selectors: Selectors, job_id: str, timeout=2) -> object:
        """
        Wait for job details to load
        :param driver: webdriver
        :param job_id: str
        :param timeout: int
        :return: object
        """
        elapsed = 0
        sleep_time = 0.05

        while elapsed < timeout:
            loaded = driver.execute_script(
                '''
                    const detailsPanel = document.querySelector(arguments[1]);
                    const description = document.querySelector(arguments[2]);
                    return detailsPanel && detailsPanel.innerHTML.includes(arguments[0]) &&
                        description && description.innerText.length > 0;    
                ''',
                job_id,
                selectors.detailsPanel,
                selectors.description)

            if loaded:
                return {'success': True}

            sleep(sleep_time)
            elapsed += sleep_time

        return {'success': False, 'error': 'Timeout on loading job details'}

    @staticmethod
    def __load_more_jobs(driver: webdriver, selectors: Selectors, job_links_tot: int, timeout=2) -> object:
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
                    selectors.seeMoreJobs)

            loaded = driver.execute_script(
                '''
                    window.scrollTo(0, document.body.scrollHeight);
                    return document.querySelectorAll(arguments[0]).length > arguments[1];
                ''',
                selectors.jobs,
                job_links_tot)

            if loaded:
                return {'success': True}

            sleep(sleep_time)
            elapsed += sleep_time

        return {'success': False, 'error': 'Timeout on loading more jobs'}

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

    def run(
        self,
        driver: webdriver,
        search_url: str,
        query: Query,
        location: str,
        page_offset: int,
    ) -> None:
        """
        Run scraper
        :param driver: webdriver
        :param cdp: CDP
        :param search_url: str
        :param query: Query
        :param location: str
        :param page_offset: int
        :return: None
        """

        warn('[AnonymousStrategy]', 'This run strategy is no longer supported')

        tag = f'[{query.query}][{location}]'
        processed = 0

        info(tag, f'Opening {search_url}')
        driver.get(search_url)

        # Verify if redirected to auth wall
        if AnonymousStrategy.__require_authentication(driver):
            error('Scraper failed to run in anonymous mode, authentication may be necessary for this environment. '
                  'Please check the documentation on how to use an authenticated session.')
            return

        # Linkedin seems to randomly load two different set of selectors:
        # the following hack tries to switch between the two sets
        Selectors.switch_selectors = False
        selectors = Selectors()

        try:
            info(tag, 'Trying first selectors set')
            debug(tag, 'Waiting selector', selectors.container)
            WebDriverWait(driver, 3).until(ec.presence_of_element_located((By.CSS_SELECTOR, selectors.container)))
            # First set of selectors confirmed
        except:
            try:
                # Try to load second set of selectors
                info(tag, 'Trying second selectors set')
                Selectors.switch_selectors = True
                debug(tag, 'Waiting selector', selectors.container)
                WebDriverWait(driver, 3).until(ec.presence_of_element_located((By.CSS_SELECTOR, selectors.container)))
                # Second set of selectors confirmed
            except:
                info(tag, 'Failed to load container selector, skip')
                return

        job_index = 0

        info(tag, 'OK')
        info(tag, 'Starting pagination loop')

        # Pagination loop
        while processed < query.options.limit:
            AnonymousStrategy.__accept_cookies(driver, tag)

            jobs_tot = driver.execute_script('return document.querySelectorAll(arguments[0]).length;', selectors.jobs)

            if jobs_tot == 0:
                info(tag, 'No jobs found, skip')
                break

            info(tag, f'Found {jobs_tot} jobs')

            # Jobs loop
            while job_index < jobs_tot and processed < query.options.limit:
                sleep(self.scraper.slow_mo)
                tag = f'[{query.query}][{location}][{processed + 1}]'

                # Extract job main fields and navigate job link
                debug(tag, 'Evaluating selectors', [
                    selectors.jobs,
                    selectors.links,
                    selectors.companies,
                    selectors.places,
                    selectors.dates])

                try:
                    job_id, job_link, job_title, job_company, job_place, job_date = driver.execute_script(
                        '''
                            const index = arguments[0];
                            const job = document.querySelectorAll(arguments[1])[index];
                            const link = job.querySelector(arguments[2]);
                            
                            // Click job link and scroll
                            link.scrollIntoView();
                            link.click();
                            const linkUrl = link.getAttribute("href");
                            
                            // Extract job id
                            let jobId = '';
                            
                            // First set of selectors                            
                            jobId = job.getAttribute('data-id');
                            
                            // Second set of selectors
                            if (!jobId) {
                                jobId = job.querySelector(arguments[2])
                                    .parentElement.getAttribute('data-entity-urn').split(':').splice(-1)[0];
                            }
                                                                                
                            return [
                                jobId,
                                linkUrl,
                                job.querySelector(arguments[2]).innerText,
                                job.querySelector(arguments[3]).innerText,
                                job.querySelector(arguments[4]).innerText,
                                job.querySelector(arguments[5]).getAttribute('datetime')
                            ];
                        ''',
                        job_index,
                        selectors.jobs,
                        selectors.links,
                        selectors.companies,
                        selectors.places,
                        selectors.dates)

                    # Wait for job details to load
                    debug(tag, f'Loading details of job {job_id}')
                    load_result = AnonymousStrategy.__load_job_details(driver, selectors, job_id)

                    if not load_result['success']:
                        error(tag, load_result['error'])
                        job_index += 1
                        continue

                    # Extract description
                    debug(tag, 'Evaluating selectors', [selectors.description])

                    job_description, job_description_html = driver.execute_script(
                        '''
                            const el = document.querySelector(arguments[0]);
                        
                            return [
                                el.innerText,
                                el.outerHTML    
                            ];
                        ''',
                        selectors.description)

                    # Extract apply link
                    debug(tag, 'Evaluating selectors', [selectors.applyLink])

                    job_apply_link = driver.execute_script(
                        '''
                            const applyBtn = document.querySelector(arguments[0]);
                            return applyBtn ? applyBtn.getAttribute("href") : '';
                        ''',
                        selectors.applyLink)

                except BaseException as e:
                    error(tag, e, traceback.format_exc())
                    self.scraper.emit(Events.ERROR, str(e) + '\n' + traceback.format_exc())
                    job_index += 1
                    continue

                data = EventData(
                    query=query.query,
                    location=location,
                    job_id=job_id,
                    job_index=job_index,
                    title=job_title,
                    company=job_company,
                    place=job_place,
                    date=job_date,
                    link=job_link,
                    apply_link=job_apply_link,
                    description=job_description,
                    description_html=job_description_html)

                info(tag, 'Processed')

                job_index += 1
                processed += 1

                self.scraper.emit(Events.DATA, data)

                # Try fetching more jobs
                if processed < query.options.limit and job_index == jobs_tot:
                    jobs_tot = driver.execute_script('return document.querySelectorAll(arguments[0]).length;',
                                                     selectors.jobs)

            # Check if we reached the limit of jobs to process
            if processed == query.options.limit:
                break

            # Check if we need to paginate
            info(tag, 'Checking for new jobs to load...')
            load_result = AnonymousStrategy.__load_more_jobs(driver, selectors, jobs_tot)

            if not load_result['success']:
                info(tag, "Couldn't find more jobs for the running query")
                break
