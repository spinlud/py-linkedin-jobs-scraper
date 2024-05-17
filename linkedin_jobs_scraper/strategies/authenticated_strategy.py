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
from ..events import Events, EventData, EventMetrics
from ..exceptions import InvalidCookieException

from ..strategies import strategies_scripts
from ..strategies.strategies_scripts import Selectors


class AuthenticatedStrategy(Strategy):
    def __init__(self, scraper: 'LinkedinScraper'):
        super().__init__(scraper)
    
    @staticmethod
    def __is_authenticated_session(driver: webdriver, tag: str = None):
        """
        Return True if authenticated session cookie is set, False otherwise
        :param driver: webdriver
        :return:
        """
        if driver.get_cookie('li_at') is not None:
            warn(tag, 'Session is no longer valid, this may cause the scraper to fail')
        return driver.get_cookie('li_at') is not None
    
    @staticmethod
    def __verify_session(driver: webdriver, tag: str = None):
        # Verify session in loop
        if driver.get_cookie('li_at') is None:
            # Try to Set authentication cookie
            info(tag, 'Setting authentication cookie')
            
            try:
                driver.add_cookie({
                        'name':   'li_at',
                        'value':  Config.LI_AT_COOKIE,
                        'domain': '.www.linkedin.com'
                        })
            except BaseException as e:
                error(tag, e)
                error(tag, traceback.format_exc())
                return
        
        if driver.get_cookie('li_at') is None:
            message = 'The provided session cookie is invalid. ' \
                      'Check the documentation on how to obtain a valid session cookie.'
            raise InvalidCookieException(message)
        else:
            debug(tag, 'Session is valid')
    
    @staticmethod
    def __login(driver: webdriver, tag: str = None):
        email = Config.LINKEDIN_EMAIL
        password = Config.LINKEDIN_PASS
        
        if None not in [email, password]:
            info(tag, 'Setting authentication login')
            driver.get("https://www.linkedin.com/login")
            WebDriverWait(driver, 5).until(
                    ec.presence_of_element_located((By.ID, Selectors.USERNAME)))  # By.CSS_SELECTOR
            
            email_elem = driver.find_element(By.ID, "username")
            email_elem.send_keys(email)
            
            password_elem = driver.find_element(By.ID, "password")
            password_elem.send_keys(password)
            password_elem.submit()
            
            WebDriverWait(driver, 5).until(
                    ec.presence_of_element_located((By.CLASS_NAME, Selectors.VERIFY_LOGIN_ID)))
        
        return driver
    
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
    def __accept_privacy(driver: webdriver, tag: str) -> None:
        """
        Accept privacy
        :param driver:
        :param tag:
        :return:
        """
        
        try:
            driver.execute_script(
                    '''
                        const privacyButton = Array.from(document.querySelectorAll(arguments[0]))
                            .find(e => e.innerText === 'Accept');
                        
                        if (privacyButton) {
                            privacyButton.click();
                        }
                    ''',
                    Selectors.privacyAcceptBtn
                    )
        except BaseException as e:
            debug(tag, 'Failed to accept privacy')
    
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
    
    @staticmethod
    def __extract_apply_link(tag: str, driver: webdriver, timeout=4):
        try:
            elapsed = 0
            sleep_time = 0.1
            current_url = driver.current_url
            
            debug(tag, 'Evaluating selectors', [Selectors.applyBtn])
            
            driver.execute_script(
                    r'''
                        const applyBtn = document.querySelector(arguments[0]);
    
                        if (applyBtn) {
                            applyBtn.click();
                            return true;
                        }
    
                        return false;
                    ''',
                    Selectors.applyBtn
                    )
            
            if len(driver.window_handles) > 1:
                debug(tag, 'Try extracting apply link')
                
                while elapsed < timeout:
                    targets_result = driver.execute_cdp_cmd('Target.getTargets', {})
                    
                    if targets_result and 'targetInfos' in targets_result and len(targets_result['targetInfos']) > 0:
                        for target in targets_result['targetInfos']:
                            if target['attached'] and target['type'] == 'page' and target['url'] and \
                                    target['url'] != current_url:
                                driver.execute_cdp_cmd('Target.closeTarget', {'targetId': target['targetId']})
                                return {'success': True, 'apply_link': target['url']}
                    
                    sleep(sleep_time)
                    elapsed += sleep_time
                
                warn(tag, 'Failed to extract apply link: timeout')
                return {'success': False, 'error': 'Timeout'}
            return {'success': False, 'error': 'No handle'}
        except BaseException as e:
            warn(tag, 'Failed to extract apply link', e)
            return {'success': False, 'error': str(e)}
    
    def run(
            self,
            driver: webdriver,
            search_url: str,
            query: Query,
            location: str,
            page_offset: int,
            ) -> None:
        """
        Run strategy
        :param driver: webdriver
        :param cdp: CDP
        :param search_url: str
        :param query: Query
        :param location: str
        :param page_offset: int
        :return: None
        """
        
        tag = f'[{query.query}][{location}]'
        
        metrics = EventMetrics()
        
        pagination_index = page_offset
        pagination_size = 25
        
        # Open main page first to verify/set the session
        debug(tag, f'Opening {HOME_URL}')
        # try:
        #     driver = AuthenticatedStrategy.__login(driver, tag)
        # except:
        #     sleep(self.scraper.slow_mo)
        driver.get(HOME_URL)
        sleep(self.scraper.slow_mo)
        
        AuthenticatedStrategy.__verify_session(driver, tag)
        
        # ***********************************************************************************************************
        # Open search url
        search_url = override_query_params(search_url, {'start': pagination_index * pagination_size})
        info(tag, f'Opening {search_url}')
        driver.get(search_url)
        sleep(self.scraper.slow_mo)
        
        # Verify session
        AuthenticatedStrategy.__is_authenticated_session(driver, tag)
        
        # Wait container
        try:
            WebDriverWait(driver, 5).until(ec.presence_of_element_located((By.CSS_SELECTOR, Selectors.container)))
        except BaseException as e:
            warn(tag, 'No jobs found, skip')
            return
        
        # Pagination loop
        while metrics.processed < query.options.limit:
            # Verify session
            AuthenticatedStrategy.__is_authenticated_session(driver, tag)
            
            AuthenticatedStrategy.__accept_cookies(driver, tag)
            AuthenticatedStrategy.__close_chat_panel(driver, tag)
            AuthenticatedStrategy.__accept_privacy(driver, tag)
            
            job_tot = driver.execute_script('return document.querySelectorAll(arguments[0]).length;', Selectors.jobs)
            
            if job_tot == 0:
                info(tag, 'No jobs found, skip')
            
            local_job_index = 0
            # Jobs loop
            while local_job_index < job_tot:
                sleep(self.scraper.slow_mo)
                tag = f'[{query.query}][{location}][{metrics.processed}]'
                
                # Try to recover focus to main page in case of unwanted tabs still open
                # (generally caused by apply link click).
                if len(driver.window_handles) > 1:
                    debug('Try closing unwanted targets')
                    try:
                        targets_result = driver.execute_cdp_cmd('Target.getTargets', {})
                        
                        # try to close other unwanted tabs (targets)
                        if targets_result and 'targetInfos' in targets_result and len(
                                targets_result['targetInfos']) > 1:
                            for target in targets_result['targetInfos']:
                                if 'linkedin.com/jobs' not in target['url'] and 'targetId' in target:
                                    debug(f'Closing target {target["url"]}')
                                    driver.execute_cdp_cmd('Target.closeTarget', {'targetId': target['targetId']})
                    finally:
                        debug('Switched to main handle')
                        driver.switch_to.window(driver.window_handles[0])
                
                try:
                    debug(tag, pagination_index, pagination_size, local_job_index, metrics.processed)
                    # Extract job main fields
                    job_id, job_link, job_title, job_company, job_company_link, \
                    job_company_img_link, job_place, job_date, job_is_promoted, reason = \
                        strategies_scripts.extract_job_main_fields(driver, tag, local_job_index, query)
                    if not job_company:
                        info(f"Scip by COMPANY [ {reason} ] avaliable: \n "
                             f"{job_title}, {job_company}, {job_place}")
                        metrics.skipped += 1
                        local_job_index += 1
                        continue
                    if not job_title:
                        info(f"Scip by TITLE [ {reason} ] avaliable: \n "
                             f"{job_title}, {job_company}, {job_place}")
                        metrics.skipped += 1
                        local_job_index += 1
                        continue
                    
                    sleep(self.scraper.slow_mo)
                    
                    # Wait for job details to load
                    debug(tag, f'Loading details job {job_id}')
                    load_result = AuthenticatedStrategy.__load_job_details(driver, job_id)
                    
                    if not load_result['success']:
                        error(tag, load_result['error'], exc_info=False)
                        info(tag, 'Failed to process')
                        metrics.failed += 1
                        local_job_index += 1
                        continue
                    
                    # *************************************************************************************************
                    # Extract Filters
                    # Promoted jobs
                    if query.options_skip.skip_promoted_jobs and job_is_promoted:
                        info(f"Scip by PROMOTED: \n "
                             f"{job_title}, {job_company}, {job_place}")
                        metrics.skipped += 1
                        local_job_index += 1
                        continue
                    
                    # Remote truly available
                    location_remote_unavailable = strategies_scripts.extract_location_remote_available(driver, tag)
                    if query.options_skip.stop_location_remote_available and location_remote_unavailable:
                        info(f"Scip by REMOTE avaliable: \n "
                             f"{job_title}, {job_company}, {job_place}")
                        metrics.skipped += 1
                        local_job_index += 1
                        continue
                    
                    # Extract required skills
                    job_required_skills, reason = strategies_scripts.extract_job_required_skills(driver, tag, query)
                    if not job_required_skills:
                        info(f"Scip by SKILLS [ {reason} ] avaliable: \n "
                             f"{job_title}, {job_company}, {job_place}")
                        metrics.skipped += 1
                        local_job_index += 1
                        continue
                    
                    # *************************************************************************************************
                    # Extract others
                    job_description, job_description_html, job_salary = strategies_scripts.extract_other(driver, tag,
                                                                                                         query)
                    if not job_description:
                        info(f"Scip by DESCRIPTION avaliable: \n "
                             f"{job_title}, {job_company}, {job_place}")
                        metrics.skipped += 1
                        local_job_index += 1
                        continue
                    
                    # Apply link
                    job_apply_link = ''
                    if query.options.apply_link:
                        apply_link_result = AuthenticatedStrategy.__extract_apply_link(tag, driver)
                        if apply_link_result['success']:
                            job_apply_link = apply_link_result['apply_link']
                    
                    data = EventData(
                            query=query.query,
                            location=location,
                            job_id=job_id,
                            job_index=metrics.processed,
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
                            skills=job_required_skills,
                            location_remote_available=location_remote_unavailable,
                            job_salary=job_salary,
                            tag=tag)
                    
                    debug(tag, 'Processed')
                    
                    metrics.processed += 1
                    local_job_index += 1
                    
                    # Emit this
                    self.scraper.emit(Events.DATA, data)
                    self.scraper.emit(Events.DATAFILE, data)
                    
                    # Try fetching more jobs on this page
                    if metrics.processed < query.options.limit and local_job_index == job_tot < pagination_size:
                        load_jobs_result = AuthenticatedStrategy.__load_jobs(driver, job_tot)
                        
                        if load_jobs_result['success']:
                            job_tot = load_jobs_result['count']
                    
                    if local_job_index == job_tot:
                        break
                
                except BaseException as e:
                    try:
                        # Verify session on error
                        AuthenticatedStrategy.__verify_session(driver, tag)
                        
                        error(tag, e, traceback.format_exc())
                        self.scraper.emit(Events.ERROR, str(e) + '\n' + traceback.format_exc())
                    finally:
                        info(tag, 'Failed to process')
                        metrics.failed += 1
                        local_job_index += 1
                    
                    continue
            # End of Job Loop
            # *************************************************************************************************
            
            tag = f'[{query.query}][{location}]'
            
            info(tag, 'No more jobs to process in this page')
            
            # Check if we reached the limit of jobs to process
            if metrics.processed == query.options.limit:
                info(tag, 'Query limit reached!')
                info(tag, 'Metrics:', str(metrics))
                self.scraper.emit(Events.METRICS, metrics)
            else:
                metrics.missed += pagination_size - local_job_index
                debug(tag, 'Metrics:', str(metrics))
                self.scraper.emit(Events.METRICS, metrics)
            
            # Try to paginate
            pagination_index += 1
            debug(tag, f'Pagination requested [{pagination_index}]')
            offset = pagination_index * pagination_size
            paginate_result = AuthenticatedStrategy.__paginate(driver, search_url, tag, offset)
            
            if not paginate_result['success']:
                info(tag, "Couldn't find more jobs for the running query")
                return
