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
from ..utils.chrome_driver import mask_headless_user_agent
from ..utils.constants import FEED_URL, HOME_URL
from ..utils.session import (REMEMBER_COOKIE_NAME, SESSION_COOKIE_NAME, get_cookie, get_session_cookie,
                             is_on_linkedin, set_remember_me_cookies, set_session_cookie,
                             wait_for_linkedin)
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

# Pause before the second attempt at opening a page of results.
PAGINATION_RETRY_DELAY = 2

# How many times a location may have its session rebuilt before it is given up on. A session
# that is refused again as soon as it has been reissued is not going to be fixed by asking a
# third time, and without a cap that pair of events loops forever.
MAX_SESSION_RECOVERIES = 2

# A navigation returns before the response carrying the session cookie is processed,
# because the driver uses a 'none' page load strategy.
SESSION_WAIT_TIMEOUT = 10

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
    signInForm = 'form.login__form, input#username, input#password, form[action*="login-submit"]'
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
        return get_session_cookie(driver) is not None

    @staticmethod
    def __is_session_lost(driver: webdriver) -> bool:
        """
        Return True when the browser is on LinkedIn and holds no session

        The two questions have to be asked together. Throttling and a retired session look
        alike - a page that will not render - and the cookie alone cannot tell them apart,
        because a throttled request leaves the browser on an error page whose jar is empty.
        Answering a 429 by authenticating again would spend a working credential on a moment
        of load shedding.

        :param driver: webdriver
        :return: bool
        """

        return is_on_linkedin(driver) and \
            not AuthenticatedStrategy.__is_authenticated_session(driver)

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
    def __wait_for_session(driver: webdriver, timeout=SESSION_WAIT_TIMEOUT) -> str | None:
        """
        Poll until the browser holds a session cookie

        The driver uses a 'none' page load strategy, so a navigation returns before the
        response that carries the cookie has been processed.

        :param driver: webdriver
        :param timeout: int
        :return: str
        """

        elapsed = 0
        sleep_time = 0.1

        while elapsed < timeout:
            li_at = get_session_cookie(driver)

            if li_at:
                return li_at

            sleep(sleep_time)
            elapsed += sleep_time

        return None

    @staticmethod
    def __recover_session(driver: webdriver, tag: str) -> str | None:
        """
        Let LinkedIn reissue the session cookie from its remember me cookie

        Requesting an authenticated route with `li_rm` present is enough: LinkedIn mints a
        fresh session with no interaction at all, which is the same mechanism behind the
        account offered on its sign in page. The bare home page does not trigger it.

        :param driver: webdriver
        :param tag: str
        :return: str the reissued session cookie, or None
        """

        info(tag, 'Asking LinkedIn to issue a session from the remember me cookie')

        try:
            driver.get(FEED_URL)
        except BaseException as e:
            warn(tag, 'Failed to open the feed while recovering the session', e)
            return None

        li_at = AuthenticatedStrategy.__wait_for_session(driver)

        if li_at:
            info(tag, 'Session issued by LinkedIn')
        else:
            # Not worth a warning on its own: the caller decides how bad this is, depending
            # on whether a supplied cookie can still carry the run
            debug(tag, 'LinkedIn did not issue a session')

        return li_at

    @staticmethod
    def __authenticate(driver: webdriver, tag: str, has_profile: bool) -> bool:
        """
        Get a session into the browser, by having one issued when that is possible

        Two credentials can be supplied, and they are not equivalent. The remember me pair
        is asked for a session, so the run starts on one LinkedIn has just minted; a bare
        `li_at` is handed over as is, and nothing can renew it once LinkedIn retires it. A
        persistent profile carries the pair on its own after an interactive sign in, which
        is why both paths end up at the same reissue.

        :param driver: webdriver
        :param tag: str
        :param has_profile: bool whether a persistent profile is in use
        :return: bool
        """

        has_remember_me = bool(get_cookie(driver, REMEMBER_COOKIE_NAME))

        # A profile that signed in interactively holds its own pair, and it is bound to the
        # browser id in that same profile: a supplied pair must not overwrite it
        if not has_remember_me:
            if Config.LI_RM_COOKIE and Config.LI_BCOOKIE:
                info(tag, 'Setting remember me cookies')
                has_remember_me = set_remember_me_cookies(driver, Config.LI_RM_COOKIE, Config.LI_BCOOKIE)
            elif Config.LI_RM_COOKIE or Config.LI_BCOOKIE:
                warn(tag, 'LI_RM_COOKIE and LI_BCOOKIE only work as a pair, ignoring the one supplied')

        if has_remember_me:
            if AuthenticatedStrategy.__recover_session(driver, tag):
                return True

            # Saying this out loud matters: the halves are valid looking on their own, so a
            # mismatched pair looks exactly like a missing one from the outside
            warn(tag, 'LinkedIn refused the remember me cookie. It only works as the pair it was '
                      'issued as, li_rm together with the bcookie from that same browser: halves '
                      'taken from different browsers are refused, as is either half alone')

        if not Config.LI_AT_COOKIE:
            if has_remember_me:
                error(tag, 'No session: the remember me cookie was refused and there is no '
                           'LI_AT_COOKIE to fall back on', exc_info=False)
            else:
                error(tag, 'No session available: set LI_RM_COOKIE with LI_BCOOKIE, sign in once with '
                           'python -m linkedin_jobs_scraper.login --user-data-dir <path>, or fall back '
                           'to LI_AT_COOKIE', exc_info=False)
            return False

        if has_profile:
            # A profile seeded by injecting a session cookie never receives the remember me
            # pair, so it cannot have a retired session replaced
            warn(tag, 'Falling back to the supplied session cookie, which cannot be renewed. Supply '
                      'LI_RM_COOKIE with LI_BCOOKIE, or sign in once with '
                      'python -m linkedin_jobs_scraper.login, to make the session recover on its own')

        info(tag, 'Setting authentication cookie')

        return set_session_cookie(driver, Config.LI_AT_COOKIE)

    @staticmethod
    def __wait_for_container(driver: webdriver, timeout=CONTAINER_WAIT_TIMEOUT) -> bool:
        """
        Wait for the results list to be rendered
        :param driver: webdriver
        :param timeout: int
        :return: bool
        """

        try:
            WebDriverWait(driver, timeout).until(
                ec.presence_of_element_located((By.CSS_SELECTOR, Selectors.container)))
            return True
        except BaseException:
            return False

    def __open_results(self, driver: webdriver, tag: str, search_url: str, has_profile: bool) -> bool:
        """
        Open a page of results, authenticating once more if LinkedIn refuses

        A refusal here is not a verdict on what the caller supplied. LinkedIn refuses in two
        ways - clearing the session cookie, or leaving it in the jar and serving the logged
        out page - and in both a persistent profile holding a retired cookie would keep
        winning over the fresh credentials the caller just supplied, since the jar is
        consulted first. So the jar is emptied of its session and the credentials get one
        chance to produce another.

        This is the whole session recovery ladder, so it is also the only place that can say
        a session could not be rebuilt: `INVALID_SESSION` is emitted here, next to the
        exception that aborts the run, and nowhere else.

        :param driver: webdriver
        :param tag: str
        :param search_url: str
        :param has_profile: bool
        :return: bool True if the results list rendered
        """

        info(tag, f'Opening {search_url}')
        driver.get(search_url)
        sleep(self.scraper.slow_mo)

        # A cleared cookie is a refusal on its own, and waiting the whole container timeout
        # out on a page that cannot render one only delays saying so
        if AuthenticatedStrategy.__is_authenticated_session(driver):
            if AuthenticatedStrategy.__wait_for_container(driver):
                return True

            # Distinguish the two, because "no jobs found" on its own sends debugging in the
            # wrong direction
            if not AuthenticatedStrategy.__is_guest_page(driver):
                warn(tag, f'Results container {Selectors.container} never appeared, skip')
                debug(tag, AuthenticatedStrategy.__describe_page(driver))
                return False

        # A page that never arrived is not a refusal, and its empty cookie jar is not a
        # verdict on the session. Throttling lands here, and re-authenticating over it would
        # spend a good credential to no purpose.
        if not is_on_linkedin(driver):
            warn(tag, 'The page did not load, so nothing can be said about the session, skip')
            debug(tag, AuthenticatedStrategy.__describe_page(driver))
            return False

        warn(tag, 'LinkedIn refused the session: it was retired, or the requests are being '
                  'throttled. Authenticating again')

        try:
            driver.delete_cookie(SESSION_COOKIE_NAME)
        except BaseException:
            pass

        # Cookies can only be injected for the domain the browser is on, and the refusal may
        # have redirected it anywhere
        driver.get(HOME_URL)
        sleep(self.scraper.slow_mo)

        if not wait_for_linkedin(driver):
            warn(tag, 'The browser never landed back on LinkedIn, so no credential can be '
                      'injected, skip')
            debug(tag, AuthenticatedStrategy.__describe_page(driver))
            return False

        if not AuthenticatedStrategy.__authenticate(driver, tag, has_profile):
            return False

        info(tag, f'Opening {search_url}')
        driver.get(search_url)
        sleep(self.scraper.slow_mo)

        if AuthenticatedStrategy.__wait_for_container(driver):
            return True

        if not AuthenticatedStrategy.__is_session_lost(driver):
            # A session LinkedIn accepted but a page it would not render, or a page that
            # never arrived at all: throttling looks exactly like both, and neither is worth
            # aborting the whole run for
            warn(tag, 'Still no results after authenticating again, skip')
            debug(tag, AuthenticatedStrategy.__describe_page(driver))
            return False

        self.scraper.emit(Events.INVALID_SESSION)

        raise InvalidCookieException(
            'LinkedIn refused every session available and would not issue another. Check the '
            'documentation on how to obtain a valid session cookie.')

    @staticmethod
    def __describe_page(driver: webdriver) -> str:
        """
        Summarize what the browser is actually showing

        Several very different failures look alike from the outside - a guest page, a
        checkpoint, an empty result set, a load that never finished - so a failure worth
        reporting is worth describing.

        :param driver: webdriver
        :return: str
        """

        try:
            state = driver.execute_script(
                r'''
                    const text = (document.body && document.body.innerText || '')
                        .replace(/[\n\r\t ]+/g, ' ')
                        .trim();

                    return {
                        readyState: document.readyState,
                        url: window.location.href,
                        title: document.title,
                        container: !!document.querySelector(arguments[0]),
                        guest: !!document.querySelector(arguments[1]),
                        items: document.querySelectorAll(arguments[2]).length,
                        text: text.slice(0, 220),
                    };
                ''',
                Selectors.container,
                Selectors.guestMarkers,
                Selectors.job_items)
        except BaseException as e:
            return f'page state unavailable ({e})'

        if not state:
            return 'page state unavailable (document is being replaced)'

        return f"readyState={state['readyState']} container={state['container']} " \
               f"guest={state['guest']} items={state['items']} title={state['title']!r} " \
               f"url={state['url']} text={state['text']!r}"

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
    def __paginate(driver: webdriver, url: str, tag: str, timeout=CONTAINER_WAIT_TIMEOUT) -> object:
        """
        Open the next page of results and wait for its list to be rendered

        The wait has to tolerate a full page load, not just a client side list update: the
        results list is replaced from scratch, so for a while the page holds neither the
        old items nor the new ones.

        :param driver: webdriver
        :param url: str the page to open, carrying its own `start` offset
        :param tag: str
        :param timeout: int
        :return: object
        """

        info(tag, f'Opening {url}')

        try:
            driver.get(url)
        except BaseException as e:
            warn(tag, 'Failed to open the next page', e)
            return {'success': False, 'error': str(e)}

        elapsed = 0
        sleep_time = 0.05  # 50 ms
        items = 0

        debug(tag, 'Waiting for new jobs to load')

        while elapsed < timeout:
            try:
                items = driver.execute_script(
                    '''
                        return document.querySelectorAll(arguments[0]).length;
                    ''',
                    Selectors.job_items)
            except BaseException:
                # The document is replaced while the next page loads
                items = None

            if items:
                debug(tag, f'Next page rendered {items} items in {round(elapsed, 2)}s')
                return {'success': True}

            sleep(sleep_time)
            elapsed += sleep_time

        return {'success': False,
                'error': f'Timeout on pagination: no item matched {Selectors.job_items} in {timeout}s. '
                         f'{AuthenticatedStrategy.__describe_page(driver)}'}

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

        # Both the masking and the cookies need the browser to be on a LinkedIn page: client
        # hints are not exposed outside a secure context, and a cookie can only be injected
        # for the domain of the document on screen
        if not wait_for_linkedin(driver):
            warn(tag, 'The browser never landed on LinkedIn, skip')
            debug(tag, AuthenticatedStrategy.__describe_page(driver))
            return

        # This first page is the only one requested before the session cookie is in place,
        # so it is where the headless User-Agent can still be replaced without any
        # authenticated request having carried it
        mask_headless_user_agent(driver)

        has_profile = bool(self.scraper.user_data_dir)

        # A session already in the jar, which is what a persistent profile provides, wins
        # over any supplied credential. Only a profile can be carrying one, so only then is
        # it worth waiting for the navigation to deliver it.
        if has_profile:
            AuthenticatedStrategy.__wait_for_session(driver)

        if not AuthenticatedStrategy.__is_authenticated_session(driver):
            if not AuthenticatedStrategy.__authenticate(driver, tag, has_profile):
                return

        # Open search url
        current_url = override_query_params(search_url, {'start': pagination_index * PAGINATION_SIZE})

        if not self.__open_results(driver, tag, current_url, has_profile):
            return

        # A page is re-opened whenever the session has to be rebuilt part way through it, so
        # the jobs already delivered are remembered for the whole location rather than per
        # page. It also covers LinkedIn re-rendering a card it has already shown.
        processed_ids = set()
        recoveries = 0

        # Pagination loop
        while metrics.processed < query.options.limit:
            # Verify session in loop
            if AuthenticatedStrategy.__is_session_lost(driver):
                if recoveries >= MAX_SESSION_RECOVERIES:
                    warn(tag, f'Session refused again after {recoveries} recoveries, skip')
                    return

                recoveries += 1
                warn(tag, 'Session is no longer valid, rebuilding it and re-opening this page')

                # Every credential is tried again here, and the page is opened once more with
                # whatever session comes out of it
                if not self.__open_results(driver, tag, current_url, has_profile):
                    return

                continue

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
            session_lost = False

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

                if job_id in processed_ids:
                    debug(tag, f'Job {job_id} was already processed, skip')
                    continue

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
                    processed_ids.add(job_id)

                    self.scraper.emit(Events.DATA, data)

                except BaseException as e:
                    # Every remaining job of this page would fail the same way, so a lost
                    # session leaves the page to the pagination loop, which rebuilds it
                    session_lost = AuthenticatedStrategy.__is_session_lost(driver)

                    try:
                        error(tag, e, traceback.format_exc())
                        self.scraper.emit(Events.ERROR, str(e) + '\n' + traceback.format_exc())
                    finally:
                        info(tag, 'Failed to process')
                        metrics.failed += 1

                    if session_lost:
                        break

                    continue

            tag = f'[{query.query}][{location}]'

            # The jobs left on this page are not missed, they are retried: the top of this
            # loop rebuilds the session and opens the same page again
            if session_lost:
                continue

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
            current_url = override_query_params(search_url, {'start': pagination_index * PAGINATION_SIZE})
            paginate_result = AuthenticatedStrategy.__paginate(driver, current_url, tag)

            # The next page does not always render on the first attempt, and giving up
            # there costs every result past the first page
            if not paginate_result['success']:
                warn(tag, 'Pagination failed, retrying', paginate_result['error'])
                sleep(PAGINATION_RETRY_DELAY)
                paginate_result = AuthenticatedStrategy.__paginate(driver, current_url, tag)

            if not paginate_result['success']:
                # A page that will not render is usually just a page that will not render,
                # so the session is only questioned once pagination has failed twice - and
                # even then, only if the browser got far enough for the answer to mean
                # something. A 429 leaves it on an error page with an empty cookie jar.
                if AuthenticatedStrategy.__is_session_lost(driver) or \
                        AuthenticatedStrategy.__is_guest_page(driver):
                    if recoveries >= MAX_SESSION_RECOVERIES:
                        warn(tag, f'Session refused again after {recoveries} recoveries, skip')
                        return

                    recoveries += 1
                    warn(tag, 'The session was refused while paginating, rebuilding it')

                    if not self.__open_results(driver, tag, current_url, has_profile):
                        return

                    continue

                info(tag, "Couldn't find more jobs for the running query", paginate_result['error'])
                return
