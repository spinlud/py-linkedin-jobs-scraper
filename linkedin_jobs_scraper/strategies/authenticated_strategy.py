import traceback
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
from ..utils.url import get_location, override_query_params
from ..utils.text import normalize_spaces
from ..events import Events, EventData, EventMetrics
from ..exceptions import InvalidCookieException


# Attribute carrying the job id on each item of the results list. It is set on every
# item, including the ones whose card LinkedIn has not rendered yet, which makes it the
# only stable way to address a job in the virtualized list.
JOB_ID_ATTRIBUTE = 'data-occludable-job-id'

# Number of results LinkedIn serves per page, used to build the `start` query param.
PAGINATION_SIZE = 25

# The results container is rendered by client side JavaScript and the driver uses a
# 'none' page load strategy, so this wait has to tolerate a slow first paint.
CONTAINER_WAIT_TIMEOUT = 15


class Selectors(NamedTuple):
    container = '.scaffold-layout__list'
    chatPanel = '.msg-overlay-list-bubble'
    jobs = 'div.job-card-container'
    job_items = f'.scaffold-layout__list li[{JOB_ID_ATTRIBUTE}]'
    link = 'a.job-card-container__link'
    applyBtn = 'button.jobs-apply-button[role="link"]'
    title = '.artdeco-entity-lockup__title'
    company = '.artdeco-entity-lockup__subtitle'
    company_link = '.job-details-jobs-unified-top-card__company-name a'
    place = '.artdeco-entity-lockup__caption'
    date = 'time'
    date_text = '.job-details-jobs-unified-top-card__tertiary-description-container'
    description = '.jobs-description'
    detailsPanel = '.jobs-search__job-details--container'
    insights = '.job-details-fit-level-preferences button'
    globalAlertDismissBtn = 'button.artdeco-global-alert__dismiss'
    appShell = '.scaffold-layout, .global-nav'
    guestMarkers = '.authwall, #artdeco-global-alert-container .artdeco-global-alert--eu-cookie-consent, ' \
                   '.guest-homepage, form.login__form, .base-serp-page'


def get_job_item_selector(job_id: str) -> str:
    """
    Build the selector addressing a single item of the results list by its job id
    :param job_id: str
    :return: str
    """
    return f'{Selectors.container} li[{JOB_ID_ATTRIBUTE}="{job_id}"]'


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
    def __is_guest_page(driver: webdriver) -> bool:
        """
        Return True if the page rendered is the logged out one

        A cookie sitting in the jar does not mean LinkedIn honoured it, so the rendered
        page is what tells authenticated from guest apart.

        :param driver: webdriver
        :return: bool
        """

        try:
            return driver.execute_script(
                '''
                    return !document.querySelector(arguments[0]) &&
                        !!document.querySelector(arguments[1]);
                ''',
                Selectors.appShell,
                Selectors.guestMarkers)
        except BaseException:
            return False

    @staticmethod
    def __get_job_ids(driver: webdriver) -> list:
        """
        Return the ids of every job in the current results page, in display order
        :param driver: webdriver
        :return: list
        """

        try:
            job_ids = driver.execute_script(
                '''
                    return Array.from(document.querySelectorAll(arguments[0]))
                        .map(e => e.getAttribute(arguments[1]))
                        .filter(e => e);
                ''',
                Selectors.job_items,
                JOB_ID_ATTRIBUTE)
        except BaseException:
            return []

        # execute_script yields None while the document is being replaced, which happens
        # right after the apply link opens and closes a tab
        return job_ids if job_ids else []

    @staticmethod
    def __load_more_jobs(driver: webdriver, job_count: int, timeout=3) -> bool:
        """
        Try to make LinkedIn append more items to the results list

        The list is filled in progressively as it is scrolled, so the number of items a
        page holds is not known upfront and has to be grown until it stops changing.

        :param driver: webdriver
        :param job_count: int
        :param timeout: int
        :return: bool
        """

        elapsed = 0
        sleep_time = 0.05

        while elapsed < timeout:
            try:
                count = driver.execute_script(
                    '''
                        const items = document.querySelectorAll(arguments[0]);

                        // Scrolling the last known item into view is what makes LinkedIn
                        // append the next batch
                        if (items.length && items.length <= arguments[1]) {
                            items[items.length - 1].scrollIntoView({block: 'end'});
                        }

                        return items.length;
                    ''',
                    Selectors.job_items,
                    job_count)
            except BaseException:
                count = None

            if count is not None and count > job_count:
                return True

            sleep(sleep_time)
            elapsed += sleep_time

        return False

    @staticmethod
    def __load_job_card(driver: webdriver, job_id: str, timeout=5) -> object:
        """
        Wait for the card of a job to be rendered, scrolling it into view

        The results list is virtualized: only the items close to the viewport hold a
        rendered card, so an item must be brought into view before any of its fields
        can be read.

        :param driver: webdriver
        :param job_id: str
        :param timeout: int
        :return: object
        """

        elapsed = 0
        sleep_time = 0.05

        while elapsed < timeout:
            rendered = driver.execute_script(
                '''
                    const item = document.querySelector(arguments[0]);

                    if (!item) {
                        return false;
                    }

                    if (item.querySelector(arguments[1])) {
                        return true;
                    }

                    item.scrollIntoView({block: 'center'});
                    return false;
                ''',
                get_job_item_selector(job_id),
                Selectors.jobs)

            if rendered:
                return {'success': True}

            sleep(sleep_time)
            elapsed += sleep_time

        return {'success': False, 'error': f'Timeout on rendering job card {job_id}'}

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
                    Selectors.job_items)

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
    def __dismiss_global_alert(driver: webdriver, tag: str) -> None:
        """
        Dismiss the global alert banner (terms and data use notices)

        The banner is matched by selector and not by button text, so dismissing it does
        not depend on the browser locale.

        :param driver:
        :param tag:
        :return:
        """

        try:
            driver.execute_script(
                '''
                    const dismissButton = document.querySelector(arguments[0]);

                    if (dismissButton) {
                        dismissButton.click();
                    }
                ''',
                Selectors.globalAlertDismissBtn
            )
        except BaseException as e:
            debug(tag, 'Failed to dismiss global alert')

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
        search_url = override_query_params(search_url, {'start': pagination_index * PAGINATION_SIZE})
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
            WebDriverWait(driver, CONTAINER_WAIT_TIMEOUT).until(
                ec.presence_of_element_located((By.CSS_SELECTOR, Selectors.container)))
        except BaseException as e:
            # The cookie is in the jar but LinkedIn may still have served the logged out
            # page, which carries no results container. Say which of the two happened,
            # because "no jobs found" on its own sends debugging in the wrong direction.
            if AuthenticatedStrategy.__is_guest_page(driver):
                warn(tag, 'LinkedIn served the logged out page: the session cookie was '
                          'rejected or the requests are being throttled. Skip')
            else:
                warn(tag, f'Results container {Selectors.container} never appeared, skip')
            return

        # Pagination loop
        while metrics.processed < query.options.limit:
            # Verify session in loop
            if not AuthenticatedStrategy.__is_authenticated_session(driver):
                warn(tag, 'Session is no longer valid, this may cause the scraper to fail')
                self.scraper.emit(Events.INVALID_SESSION)
            else:
                info(tag, 'Session is valid')

            AuthenticatedStrategy.__accept_cookies(driver, tag)
            AuthenticatedStrategy.__close_chat_panel(driver, tag)
            AuthenticatedStrategy.__dismiss_global_alert(driver, tag)

            # Jobs are addressed by id, never by their position among the rendered cards:
            # LinkedIn renders only a handful of cards at a time and drops the others from
            # the DOM, so positions shift while the loop runs. The id list itself also
            # grows as the page is scrolled, so it is re-read on every iteration.
            job_ids = []
            known_ids = set()
            next_index = 0

            # Jobs loop
            while metrics.processed < query.options.limit:
                for known_id in AuthenticatedStrategy.__get_job_ids(driver):
                    if known_id not in known_ids:
                        known_ids.add(known_id)
                        job_ids.append(known_id)

                if next_index >= len(job_ids):
                    if not AuthenticatedStrategy.__load_more_jobs(driver, len(job_ids)):
                        break
                    continue

                job_index = next_index
                job_id = job_ids[job_index]
                next_index += 1

                sleep(self.scraper.slow_mo)
                tag = f'[{query.query}][{location}][{pagination_index * PAGINATION_SIZE + job_index + 1}]'

                # Try to recover focus to main page in case of unwanted tabs still open
                # (generally caused by apply link click).
                if len(driver.window_handles) > 1:
                    debug('Try closing unwanted targets')
                    try:
                        targets_result = driver.execute_cdp_cmd('Target.getTargets', {})

                        # try to close other unwanted tabs (targets)
                        if targets_result and 'targetInfos' in targets_result and len(targets_result['targetInfos']) > 1:
                            for target in targets_result['targetInfos']:
                                # Only page targets can be closed: asking to close any other
                                # kind (service worker, browser, ...) raises instead
                                if target.get('type') != 'page' or 'targetId' not in target:
                                    continue

                                if 'linkedin.com/jobs' not in target.get('url', ''):
                                    debug(f'Closing target {target["url"]}')
                                    driver.execute_cdp_cmd('Target.closeTarget',
                                                           {'targetId': target['targetId']})
                    except BaseException as e:
                        # Cleaning up leftover tabs is best effort, it must never abort the query
                        warn(tag, 'Failed to close unwanted targets', e)
                    finally:
                        debug('Switched to main handle')
                        driver.switch_to.window(driver.window_handles[0])

                try:
                    # Wait for the card of this job to be rendered before reading it
                    load_card_result = AuthenticatedStrategy.__load_job_card(driver, job_id)

                    if not load_card_result['success']:
                        error(tag, load_card_result['error'], exc_info=False)
                        info(tag, 'Failed to process')
                        metrics.failed += 1
                        continue

                    # Extract job main fields
                    debug(tag, 'Evaluating selectors', [
                        Selectors.job_items,
                        Selectors.link,
                        Selectors.company,
                        Selectors.place,
                        Selectors.date])

                    job_link, job_title, job_company, \
                        job_company_img_link, job_place, job_date, job_is_promoted = \
                        driver.execute_script(
                            '''
                                const job = document.querySelector(arguments[0]);
                                const link = job.querySelector(arguments[1]);

                                // Click job link and scroll
                                link.scrollIntoView();
                                link.click();

                                // Extract job link (relative)
                                const protocol = window.location.protocol + "//";
                                const hostname = window.location.hostname;
                                const jobLink = protocol + hostname + link.getAttribute("href");

                                let title = "";
                                const titleElem = job.querySelector(arguments[2]);

                                if (titleElem) {
                                    // The title is duplicated in a visually hidden node for
                                    // screen readers, the strong element holds the visible one
                                    const visibleTitle = titleElem.querySelector("strong") || titleElem;

                                    title = visibleTitle.innerText
                                        .split("\\n")
                                        .map(e => e.trim())
                                        .filter(e => e.length)[0] || "";
                                }

                                let company = "";
                                const companyElem = job.querySelector(arguments[3]);

                                if (companyElem) {
                                    company = companyElem.innerText;
                                }

                                const companyImgLink = job.querySelector("img") ?
                                    job.querySelector("img").getAttribute("src") : "";

                                const place = job.querySelector(arguments[4]) ?
                                    job.querySelector(arguments[4]).innerText : "";

                                const date = job.querySelector(arguments[5]) ?
                                    job.querySelector(arguments[5]).getAttribute('datetime') : "";

                                const isPromoted = Array.from(job.querySelectorAll('li'))
                                    .find(e => e.innerText === 'Promoted') ? true : false;

                                return [
                                    jobLink,
                                    title,
                                    company,
                                    companyImgLink,
                                    place,
                                    date,
                                    isPromoted,
                                ];
                            ''',
                            get_job_item_selector(job_id),
                            Selectors.link,
                            Selectors.title,
                            Selectors.company,
                            Selectors.place,
                            Selectors.date)

                    # Promoted jobs
                    if query.options.skip_promoted_jobs and job_is_promoted:
                        info(tag, 'Skipped because promoted')
                        metrics.skipped += 1
                        continue

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
                        info(tag, 'Failed to process')
                        metrics.failed += 1
                        continue

                    # Extract date text (eg '1 week ago')
                    debug(tag, 'Evaluating selectors', [Selectors.date_text])

                    job_date_text = driver.execute_script(
                        r'''
                            const el = document.querySelector(arguments[0]);

                            if (!el) {
                                return "";
                            }

                            // The container reads "<place> · <date> · <applicants>", but any
                            // segment can be missing, so the date is matched by shape rather
                            // than by its position
                            const segments = el.innerText
                                .split('·')
                                .map(e => e.replace(/[\n\r\t ]+/g, ' ').trim())
                                .filter(e => e.length);

                            return segments.find(e => /\bago\b|just now/i.test(e)) || "";
                        ''',
                        Selectors.date_text
                    )

                    # Extract company link
                    debug(tag, 'Evaluating selectors', [Selectors.company_link])

                    job_company_link = driver.execute_script(
                        '''
                            const el = document.querySelector(arguments[0]);
                            
                            if (el) {
                                return el.getAttribute("href");
                            }
                            else {
                                return "";
                            }
                        ''',
                        Selectors.company_link
                    )

                    # Extract description
                    debug(tag, 'Evaluating selectors', [Selectors.description])

                    job_description, job_description_html = driver.execute_script(
                        '''
                            const el = document.querySelector(arguments[0]);

                            if (!el) {
                                return ["", ""];
                            }

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

                    if query.options.apply_link:
                        apply_link_result = AuthenticatedStrategy.__extract_apply_link(tag, driver)

                        if apply_link_result['success']:
                            job_apply_link = apply_link_result['apply_link']

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
                        date_text=job_date_text,
                        link=job_link,
                        apply_link=job_apply_link,
                        description=job_description,
                        description_html=job_description_html,
                        insights=job_insights)

                    info(tag, 'Processed')

                    metrics.processed += 1

                    self.scraper.emit(Events.DATA, data)

                except BaseException as e:
                    try:
                        # Verify session on error
                        if not AuthenticatedStrategy.__is_authenticated_session(driver):
                            warn(tag, 'Session is no longer valid, this may cause the scraper to fail')
                            self.scraper.emit(Events.INVALID_SESSION)

                        error(tag, e, traceback.format_exc())
                        self.scraper.emit(Events.ERROR, str(e) + '\n' + traceback.format_exc())
                    finally:
                        info(tag, 'Failed to process')
                        metrics.failed += 1

                    continue

            tag = f'[{query.query}][{location}]'

            if not job_ids:
                info(tag, 'No jobs found, skip')
                break

            info(tag, 'No more jobs to process in this page')

            # Check if we reached the limit of jobs to process
            if metrics.processed == query.options.limit:
                info(tag, 'Query limit reached!')
                info(tag, 'Metrics:', str(metrics))
                self.scraper.emit(Events.METRICS, metrics)
                break
            else:
                metrics.missed += len(job_ids) - next_index
                info(tag, 'Metrics:', str(metrics))
                self.scraper.emit(Events.METRICS, metrics)

            # Try to paginate
            pagination_index += 1
            info(tag, f'Pagination requested [{pagination_index}]')
            offset = pagination_index * PAGINATION_SIZE
            paginate_result = AuthenticatedStrategy.__paginate(driver, search_url, tag, offset)

            if not paginate_result['success']:
                info(tag, "Couldn't find more jobs for the running query")
                return
