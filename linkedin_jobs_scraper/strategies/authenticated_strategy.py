import traceback
from datetime import datetime
from random import uniform
from typing import Literal, NamedTuple
from urllib.parse import urlencode
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.remote.webdriver import WebDriver
from time import sleep
from .strategy import Strategy
from ..config import Config
from ..query import Query
from ..utils.logger import debug, info, warn, error
from ..utils.chrome_driver import mask_headless_user_agent
from ..utils.constants import FEED_URL, HOME_URL, JOBS_URL, JOBS_SEARCH_RESULTS_URL
from ..utils.location_picker import (LOCATION_CACHE, LocationPickerError, PickedLocation, location_matches,
                                     pick_location, read_applied_location)
from ..utils.session import (REMEMBER_COOKIE_NAME, SESSION_COOKIE_NAME, get_cookie, get_session_cookie,
                             is_on_linkedin, set_remember_me_cookies, set_session_cookie,
                             wait_for_linkedin)
from ..utils.session_source import missing_session_message
from ..utils.url import override_query_params
from ..utils.job_record import (JobDetails, RawJobDetails, parse_job_details, parse_job_record,
                                parse_results_total)
from ..events import Events, EventMetrics, EventBegin, EventNotFound
from ..exceptions import InvalidCookieException, LocationResolutionError


# Every job card carries a `componentkey` of this prefix followed by its job id. The class
# names on the page are generated at build time, so this key is the stable way to find a
# card and the only way to address a job.
JOB_CARD_KEY_PREFIX = 'job-card-component-ref-'

# Number of results LinkedIn serves per page, used to build the `start` query param.
PAGINATION_SIZE = 25

# LinkedIn stops serving results past start=1000, so an unlimited run (limit=0) paginates
# no further than this regardless of how many results the query reports.
MAX_RESULTS_CEILING = 1000

# Pause before the second attempt at opening a page of results.
PAGINATION_RETRY_DELAY = 2

# What LinkedIn answers a run that is going too fast with. The response carries no body, so
# Chrome replaces it with its own error page: nothing on that page can be waited for, and
# the navigation timing entry is the only thing left that still knows the status.
THROTTLED_STATUS = 429

# Waits before asking again for a page that came back throttled. Only time clears a 429, and
# a run that has already been told to slow down gets told again, so the wait grows.
# The waits are fixed because LinkedIn sends no `Retry-After` (measured).
THROTTLE_BACKOFF_DELAYS = (5, 15, 45)

# Two workers refused at the same moment must not ask again at the same moment: they would be
# refused together, wait together and collide again. The ladder keeps its shape and each wait
# is drawn around the step, rather than replacing it with a draw from zero - a 429 is cleared
# by time, so an attempt made too early is an attempt spent for nothing.
THROTTLE_BACKOFF_JITTER = 0.5

# The resource timing buffer holds 250 entries by default and silently drops everything past
# them, which a page of results fills on its own. Raising it is preferred to clearing it:
# `clearResourceTimings` would destroy timing data the page itself may be reading.
RESOURCE_TIMING_BUFFER_SIZE = 1000

# The results list is streamed in by the server, so ids are read only once the set of cards
# has held still for this long.
LIST_SETTLE_QUIET_PERIOD = 1
LIST_SETTLE_TIMEOUT = 8

# How long a card may be absent from the page before it is taken to have left it, rather
# than to be momentarily detached by a re-render.
MISSING_ITEM_GRACE = 1

# How many times a location may have its session rebuilt before it is given up on. A session
# that is refused again as soon as it has been reissued is not going to be fixed by asking a
# third time, and without a cap that pair of events loops forever.
MAX_SESSION_RECOVERIES = 2

# A navigation returns before the response carrying the session cookie is processed,
# because the driver uses a 'none' page load strategy.
SESSION_WAIT_TIMEOUT = 10

# The results are streamed in after the page shell and the driver uses a 'none' page load
# strategy, so this wait has to tolerate a slow first paint.
CONTAINER_WAIT_TIMEOUT = 15

# A single job page is a full page load, so its detail components get as long to appear as
# a page of results does.
SINGLE_JOB_PANEL_TIMEOUT = 15


class Selectors(NamedTuple):
    chatPanel = '.msg-overlay-list-bubble'
    job_cards = f'[role="button"][componentkey^="{JOB_CARD_KEY_PREFIX}"]'
    applyBtn = '[aria-label="Apply on company website"]'
    globalAlertDismissBtn = 'button.artdeco-global-alert__dismiss'
    appShell = '[data-testid="primary-nav"]'
    signInForm = 'form.login__form, input#username, input#password, form[action*="login-submit"]'
    guestMarkers = '.authwall, #artdeco-global-alert-container .artdeco-global-alert--eu-cookie-consent, ' \
                   '.guest-homepage, form.login__form, .base-serp-page'


def get_job_card_selector(job_id: str) -> str:
    '''
    Build the selector addressing the card of a job by its id
    :param job_id: str
    :return: str
    '''
    return f'[role="button"][componentkey="{JOB_CARD_KEY_PREFIX}{job_id}"]'


# Reads the job ids of the cards on the page, in display order. A card nests a second
# element carrying the same key, hence the de-duplication.
GET_JOB_IDS_SCRIPT = r'''
    const prefix = arguments[0];
    const keys = Array.from(document.querySelectorAll(`[componentkey^="${prefix}"]`))
        .map(e => e.getAttribute('componentkey').slice(prefix.length))
        .filter(e => /^\d+$/.test(e));
    return [...new Set(keys)];
'''

# Collects the raw pieces of one card for `parse_job_record`; no interpretation happens here
READ_JOB_CARD_SCRIPT = r'''
    const card = document.querySelector(arguments[0]);

    if (!card) {
        return null;
    }

    const img = card.querySelector('img');

    return {
        job_id: arguments[1],
        card_texts: Array.from(card.querySelectorAll('p')).map(e => e.innerText || ''),
        card_labels: Array.from(card.querySelectorAll('button[aria-label]'))
            .map(e => e.getAttribute('aria-label')),
        card_img: img ? (img.getAttribute('src') || '') : '',
    };
'''

# Collects the raw pieces of a job's detail components for `parse_job_details`, on the search
# panel and on the single job page alike. Everything is scoped by the job's own id: the
# id-keyed "About the job" and "About the company" components, and the top card, which is
# what precedes "About the job" in its column. Returns null until "About the job" is there.
READ_JOB_DETAILS_SCRIPT = r'''
    const jobId = arguments[0];
    const about = document.querySelector(`[componentkey="JobDetails_AboutTheJob_${jobId}"]`);

    if (!about) {
        return null;
    }

    const company = document.querySelector(`[componentkey="JobDetails_AboutTheCompany_${jobId}"]`);
    const column = about.closest('[data-testid="lazy-column"]') || document.body;
    const above = selector => Array.from(column.querySelectorAll(selector))
        .filter(e => about.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_PRECEDING);
    const img = above('img')[0];
    // The posting itself; the rest of the component is its heading and sections such as
    // "Benefits found in job post"
    const description = about.querySelector('[data-testid="expandable-text-box"]') || about;

    return {
        job_id: jobId,
        top_texts: above('p').map(e => e.innerText || ''),
        anchors: above('a').map(e => ({
            text: e.innerText || '',
            href: e.href || '',
            label: e.getAttribute('aria-label') || '',
        })),
        button_labels: above('button[aria-label]').map(e => e.getAttribute('aria-label')),
        company_img: img ? (img.getAttribute('src') || '') : '',
        description_text: description.innerText || '',
        description_html: description.innerHTML || '',
        company_texts: company
            ? Array.from(company.querySelectorAll('p, span'))
                .filter(e => e.children.length === 0)
                .map(e => e.innerText || '')
            : [],
    };
'''

# The single job page's own answer for an id that does not exist or a posting that was taken
# down: "Unable to load the page / Job id provided may not be valid or the job posting has been
# removed." The page has no id-keyed component in that state, so the text is the only marker.
JOB_NOT_FOUND_TEXT = 'Job id provided may not be valid or the job posting has been removed'

# Returns 'details' once the job's detail components are on the page, 'not-found' when the
# page says the job does not exist, null while neither
SINGLE_JOB_STATE_SCRIPT = r'''
    if (document.querySelector(`[componentkey="JobDetails_AboutTheJob_${arguments[0]}"]`)) {
        return 'details';
    }

    const main = document.querySelector('main') || document.body;
    return main && (main.innerText || '').includes(arguments[1]) ? 'not-found' : null;
'''

# What SINGLE_JOB_STATE_SCRIPT reports once the single job page has settled
SingleJobState = Literal['details', 'not-found']

# Returns the text of the results count ("48 results", "99+ results"), matched by shape
RESULTS_TOTAL_TEXT_SCRIPT = r'''
    const el = Array.from(document.querySelectorAll('p, span, h1, h2, div'))
        .find(e => e.children.length === 0 && /^[\d,]+\+? results?$/.test(e.textContent.trim()));
    return el ? el.textContent.trim() : '';
'''


def jittered_backoff(base: float) -> float:
    """
    Return a wait drawn around a step of the backoff ladder
    :param base: float the step of the ladder
    :return: float
    """

    return base * uniform(1 - THROTTLE_BACKOFF_JITTER, 1 + THROTTLE_BACKOFF_JITTER)


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
    def __get_response_status(driver: webdriver) -> int | None:
        """
        Return the HTTP status of the document the browser is showing

        The navigation timing entry survives on Chrome's own error page and still reports
        the status of the response that produced it, which is what makes a throttled reply
        recognisable: LinkedIn sends the 429 with an empty body, so by the time the page is
        on screen there is no LinkedIn document left to read it from.

        :param driver: webdriver
        :return: int the status, or None if it cannot be read
        """

        try:
            return driver.execute_script(
                '''
                    const navigation = performance.getEntriesByType('navigation')[0];

                    return navigation && navigation.responseStatus !== undefined ?
                        navigation.responseStatus : null;
                ''')
        except BaseException:
            return None

    @staticmethod
    def __is_throttled(driver: webdriver) -> bool:
        """
        Return True if the page on screen is LinkedIn refusing to serve a run going too fast
        :param driver: webdriver
        :return: bool
        """

        return AuthenticatedStrategy.__get_response_status(driver) == THROTTLED_STATUS

    @staticmethod
    def __count_throttled_resources(driver: webdriver) -> tuple[float, int] | None:
        """
        Return which document is on screen and how many of its requests LinkedIn has refused

        A navigation is not the only thing that gets throttled, and it is not even the common
        case: job details are fetched by the page rather than navigated to, so a 429 there
        never reaches `__is_throttled` and surfaces only as details that never loaded. The
        status of those fetches survives on their resource timing entries, which LinkedIn
        serves same origin, so the refusal is readable after the fact.

        The count means nothing without knowing which document made it, since the buffer
        belongs to the document and goes away with it. `performance.timeOrigin` is set when
        the document is created and needs no CDP to read, so it names the document the
        reading came from.

        :param driver: webdriver
        :return: tuple the document's time origin and the count, or None if the buffer could
                 not be read - which is not the same as a count of zero, and must not be
                 taken for one
        """

        try:
            reading = driver.execute_script(
                '''
                    return [
                        performance.timeOrigin,
                        performance.getEntriesByType('resource')
                            .filter(e => e.responseStatus === arguments[0]).length,
                    ];
                ''',
                THROTTLED_STATUS)
        except BaseException:
            return None

        # execute_script yields None while the document is being replaced, which is the same
        # answer as a buffer that could not be read
        if reading is None:
            return None

        return reading[0], reading[1]

    @staticmethod
    def __widen_resource_timings(driver: webdriver) -> None:
        """
        Let the document remember more than the first 250 requests it made
        :param driver: webdriver
        :return: None
        """

        try:
            driver.execute_script(
                'performance.setResourceTimingBufferSize(arguments[0]);',
                RESOURCE_TIMING_BUFFER_SIZE)
        except BaseException:
            pass

    def __slow_down(self, tag: str) -> None:
        """
        Report a refusal to the pacer, saying so when it makes the run slower

        This is the line an operator needs without turning debug logging on: it is the run
        announcing that it has been told to ask for less, well before the backoff has to
        rescue a page.

        :param tag: str
        :return: None
        """

        pacer = self.scraper.pacer
        before = pacer.delay
        after = pacer.throttled()

        if after > before:
            warn(tag, f'LinkedIn is throttling this run, slowing to {round(after, 2)}s between jobs')

    def __speed_up(self, tag: str) -> None:
        """
        Report a unit of work nobody refused, saying so when it makes the run faster
        :param tag: str
        :return: None
        """

        pacer = self.scraper.pacer
        before = pacer.delay
        after = pacer.clean()

        if after < before:
            info(tag, f'No refusals for a while, easing to {round(after, 2)}s between jobs')

    def __record_pace(self, metrics: EventMetrics) -> None:
        """
        Copy the state of the pacer onto the metrics about to be reported

        The pacer is per scraper and the metrics per location, so these two read as what this
        location saw of a limit that is really the whole account's.

        :param metrics: EventMetrics
        :return: None
        """

        metrics.throttled = self.scraper.pacer.throttled_count
        metrics.pace = round(self.scraper.pacer.delay, 2)

    def __observe_resources(self, driver: webdriver, tag: str,
                            baseline: tuple[float, int] | None) -> tuple[float, int] | None:
        """
        Pace the run from what the document's requests came back with

        The buffer is cumulative over the life of a document, so what matters is how it grew
        since it was last read, and only within the one document. A reading from another
        document is a new baseline and not a verdict on anything - which the count on its own
        cannot say, because a fresh document reports zero and a baseline of zero makes that
        indistinguishable from work nobody refused. Comparing the time origins settles it.

        :param driver: webdriver
        :param tag: str
        :param baseline: tuple the previous reading, or None if there has not been one
        :return: tuple the reading to compare the next one against
        """

        reading = AuthenticatedStrategy.__count_throttled_resources(driver)

        if reading is None:
            return baseline

        if baseline is None or reading[0] != baseline[0]:
            return reading

        if reading[1] < baseline[1]:
            # The same document holding fewer entries than before has cleared its own buffer,
            # which says as little about how the run is going as a document swap does
            return reading

        if reading[1] > baseline[1]:
            self.__slow_down(tag)
        else:
            self.__speed_up(tag)

        return reading

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
                error(tag, missing_session_message(), exc_info=False)
            return False

        if has_profile:
            # A profile seeded by injecting a session cookie never receives the remember me
            # pair, so it cannot have a retired session replaced
            warn(tag, 'Falling back to the supplied session cookie, which cannot be renewed. Supply '
                      'LI_RM_COOKIE with LI_BCOOKIE, or sign in once with '
                      'linkedin-jobs-scraper login, to make the session recover on its own')

        info(tag, 'Setting authentication cookie')

        return set_session_cookie(driver, Config.LI_AT_COOKIE)

    def __require_session(self, driver: webdriver, tag: str, has_profile: bool) -> None:
        """
        Authenticate before the first page, aborting the run when nothing can

        A browser that starts without a session and gets none from what was supplied - an
        empty or expired profile, no cookie, or a cookie LinkedIn refused - has nothing to
        scrape with, and every other location would end the same way. That is reported like
        any other session that cannot be rebuilt: `INVALID_SESSION`, then
        `InvalidCookieException`.

        :param driver: webdriver
        :param tag: str
        :param has_profile: bool whether a persistent profile is in use
        :return: None
        """

        if AuthenticatedStrategy.__authenticate(driver, tag, has_profile):
            return

        self.scraper.emit(Events.INVALID_SESSION)

        raise InvalidCookieException(
            'No usable session: the browser holds none and none could be established from the '
            'credentials available. Check the documentation on how to sign in.')

    @staticmethod
    def __wait_for_container(driver: webdriver, timeout=CONTAINER_WAIT_TIMEOUT) -> bool:
        '''
        Wait for the results page to render: a job card, or the results count of a search
        that matched nothing
        :param driver: webdriver
        :param timeout: int
        :return: bool
        '''

        elapsed = 0
        sleep_time = 0.1

        while elapsed < timeout:
            try:
                rendered = driver.execute_script(
                    'return !!document.querySelector(arguments[0]);', Selectors.job_cards) or \
                    bool(driver.execute_script(RESULTS_TOTAL_TEXT_SCRIPT))
            except BaseException:
                # The document is being replaced
                rendered = False

            if rendered:
                return True

            sleep(sleep_time)
            elapsed += sleep_time

        return False

    def __open_and_wait(self, driver: webdriver, tag: str, url: str, wait) -> bool:
        """
        Open a url and wait for its page, asking again while LinkedIn answers with a throttle

        A 429 is not a verdict on anything - not on the session, not on the selectors - and
        it is the one failure that time alone fixes, so it is the one failure worth sitting
        through. Every other outcome is handed straight back to the caller, which knows what
        an unrendered page means where it stands.

        :param driver: webdriver
        :param tag: str
        :param url: str
        :param wait: callable taking the driver and returning whether the page arrived
        :return: bool
        """

        for delay in (0, *THROTTLE_BACKOFF_DELAYS):
            if delay:
                waited = jittered_backoff(delay)
                warn(tag, f'LinkedIn is throttling this run (HTTP {THROTTLED_STATUS}), '
                          f'waiting {round(waited, 1)}s before asking again')
                sleep(waited)

            info(tag, f'Opening {url}')

            try:
                driver.get(url)
            except BaseException as e:
                warn(tag, 'Failed to open the page', e)
                return False

            sleep(self.scraper.pacer.delay)

            if wait(driver):
                AuthenticatedStrategy.__widen_resource_timings(driver)

                # A page that arrived is deliberately not reported as clean work. The unit the
                # pacer eases on is a job, and there are far more jobs than navigations, so
                # counting these too would quietly shorten the run of clean work that easing
                # has to be earned by.
                return True

            if not AuthenticatedStrategy.__is_throttled(driver):
                return False

            # One report per refused attempt, so the pacer and the backoff count the same
            # events: the backoff waits this one out, the pacer makes the next one less likely
            self.__slow_down(tag)

        warn(tag, f'LinkedIn kept throttling this run after {len(THROTTLE_BACKOFF_DELAYS)} waits. '
                  f'Raise slow_mo, or lower max_workers, to ask for less')

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

        This is the whole session recovery ladder, so it is the only place that can say a
        session could not be rebuilt part way through a run: `INVALID_SESSION` is emitted
        here, next to the exception that aborts the run. `__require_session` does the same
        for a run that never had a session to begin with.

        :param driver: webdriver
        :param tag: str
        :param search_url: str
        :param has_profile: bool
        :return: bool True if the results list rendered
        """

        def has_results(d: webdriver) -> bool:
            # A cleared cookie is a refusal on its own, and waiting the whole container
            # timeout out on a page that cannot render one only delays saying so
            return AuthenticatedStrategy.__is_authenticated_session(d) and \
                AuthenticatedStrategy.__wait_for_container(d)

        if self.__open_and_wait(driver, tag, search_url, has_results):
            return True

        # Distinguish the two, because "no jobs found" on its own sends debugging in the
        # wrong direction
        if AuthenticatedStrategy.__is_authenticated_session(driver) and \
                not AuthenticatedStrategy.__is_guest_page(driver):
            warn(tag, 'The results page never rendered a job card or a results count, skip')
            debug(tag, AuthenticatedStrategy.__describe_page(driver))
            return False

        # A page that never arrived is not a refusal, and its empty cookie jar is not a
        # verdict on the session. Throttling that outlasted every wait lands here, and
        # re-authenticating over it would spend a good credential to no purpose.
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
        sleep(self.scraper.pacer.delay)

        if not wait_for_linkedin(driver):
            warn(tag, 'The browser never landed back on LinkedIn, so no credential can be '
                      'injected, skip')
            debug(tag, AuthenticatedStrategy.__describe_page(driver))
            return False

        if not AuthenticatedStrategy.__authenticate(driver, tag, has_profile):
            return False

        if self.__open_and_wait(driver, tag, search_url, AuthenticatedStrategy.__wait_for_container):
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
        '''
        Summarize what the browser is actually showing

        Several very different failures look alike from the outside - a guest page, a
        checkpoint, an empty result set, a load that never finished - so a failure worth
        reporting is worth describing.

        :param driver: webdriver
        :return: str
        '''

        try:
            state = driver.execute_script(
                r'''
                    const text = (document.body && document.body.innerText || '')
                        .replace(/[\n\r\t ]+/g, ' ')
                        .trim();

                    const navigation = performance.getEntriesByType('navigation')[0];

                    return {
                        readyState: document.readyState,
                        status: navigation && navigation.responseStatus !== undefined ?
                            navigation.responseStatus : null,
                        url: window.location.href,
                        title: document.title,
                        shell: !!document.querySelector(arguments[0]),
                        guest: !!document.querySelector(arguments[1]),
                        cards: document.querySelectorAll(arguments[2]).length,
                        text: text.slice(0, 220),
                    };
                ''',
                Selectors.appShell,
                Selectors.guestMarkers,
                Selectors.job_cards)
        except BaseException as e:
            return f'page state unavailable ({e})'

        if not state:
            return 'page state unavailable (document is being replaced)'

        return f"status={state['status']} readyState={state['readyState']} " \
               f"shell={state['shell']} guest={state['guest']} cards={state['cards']} " \
               f"title={state['title']!r} url={state['url']} text={state['text']!r}"

    def __emit_begin(self, driver: webdriver, tag: str, location: str, resolved_location: str) -> None:
        '''
        Emit the BEGIN event carrying LinkedIn's total result count

        Fired once per query/location, before the pagination loop delivers any job. A count
        that cannot be read is reported as None rather than aborting the run.

        :param driver: webdriver
        :param tag: str
        :param location: str the location the search was asked for
        :param resolved_location: str
        :return: None
        '''

        try:
            text = driver.execute_script(RESULTS_TOTAL_TEXT_SCRIPT) or ''
        except BaseException:
            text = ''

        total = parse_results_total(text)
        debug(tag, f'Total results reported by LinkedIn: {text!r}')
        self.scraper.emit(Events.BEGIN, EventBegin(total=total.total, total_capped=total.capped,
                                                          location=location,
                                                          resolved_location=resolved_location))

    @staticmethod
    def __get_job_ids(driver: webdriver) -> list:
        '''
        Return the ids of every job card on the page, in display order
        :param driver: webdriver
        :return: list
        '''

        try:
            job_ids = driver.execute_script(GET_JOB_IDS_SCRIPT, JOB_CARD_KEY_PREFIX)
        except BaseException:
            return []

        # execute_script yields None while the document is being replaced, which happens
        # right after the apply link opens and closes a tab
        return job_ids if job_ids else []

    @staticmethod
    def __wait_for_stable_job_ids(
            driver: webdriver,
            timeout=LIST_SETTLE_TIMEOUT,
            quiet_period=LIST_SETTLE_QUIET_PERIOD) -> list:
        '''
        Return the ids of the job cards once their set has stopped changing

        A page renders all its cards at once, but they are streamed in, so a read taken
        while the stream is still arriving sees a part of the page. A full batch held still
        for the quiet period is believed; short of that only the timeout can tell a page
        still arriving from the last page of results, which genuinely holds fewer.

        :param driver: webdriver
        :param timeout: int
        :param quiet_period: int how long the set has to hold still to count as settled
        :return: list
        '''

        elapsed = 0
        sleep_time = 0.1
        quiet = 0
        job_ids = []

        while elapsed < timeout:
            current = AuthenticatedStrategy.__get_job_ids(driver)

            if current and current == job_ids:
                quiet += sleep_time

                if quiet >= quiet_period and len(job_ids) >= PAGINATION_SIZE:
                    return job_ids
            else:
                quiet = 0
                job_ids = current

            sleep(sleep_time)
            elapsed += sleep_time

        # A short list here is the last page of results, and an empty one a page holding
        # none: both are the caller's to report
        return job_ids

    @staticmethod
    def __load_job_card(driver: webdriver, job_id: str, timeout=5) -> object:
        '''
        Wait for the card of a job to be on the page, scrolling it into view

        A card that is not on the page at all is a different answer from one that fails to
        load, and the caller is told so: LinkedIn may re-render the list while the loop walks
        it, and an id read from a render that no longer exists is not a job that failed.

        :param driver: webdriver
        :param job_id: str
        :param timeout: int
        :return: object
        '''

        elapsed = 0
        sleep_time = 0.05
        missing_for = 0

        while elapsed < timeout:
            try:
                state = driver.execute_script(
                    '''
                        const card = document.querySelector(arguments[0]);

                        if (!card) {
                            return 'missing';
                        }

                        card.scrollIntoView({block: 'center'});
                        return card.querySelector('p') ? 'rendered' : 'pending';
                    ''',
                    get_job_card_selector(job_id))
            except BaseException:
                # execute_script yields nothing while the document is being replaced
                state = None

            if state == 'rendered':
                return {'success': True}

            if state == 'missing':
                missing_for += sleep_time

                if missing_for >= MISSING_ITEM_GRACE:
                    break
            else:
                missing_for = 0

            sleep(sleep_time)
            elapsed += sleep_time

        if missing_for >= MISSING_ITEM_GRACE:
            return {'success': False, 'missing': True,
                    'error': f'Job {job_id} is no longer in the results list'}

        return {'success': False, 'missing': False,
                'error': f'Timeout on rendering job card {job_id}'}

    @staticmethod
    def __read_job_details(driver: WebDriver, job_id: str, timeout: float = 5) -> RawJobDetails | None:
        '''
        Wait for the job's id-keyed detail components and read their raw pieces, on the search
        panel and on the single job page alike.

        The components stream in after their key appears: "About the job" first renders as an
        empty placeholder, and "About the company" may follow later still. The details are
        read once the description holds text and the company component has rendered; a job
        whose company component never renders is read without it when the wait runs out.

        :param driver: webdriver
        :param job_id: str
        :param timeout: float, seconds
        :return: the raw details, or None when the description never rendered
        '''

        elapsed = 0
        sleep_time = 0.05
        partial = None

        while elapsed < timeout:
            try:
                raw = driver.execute_script(READ_JOB_DETAILS_SCRIPT, job_id)
            except BaseException:
                raw = None

            if raw and raw['top_texts'] and parse_job_details(raw, datetime.now()).description:
                if raw['company_texts']:
                    return raw
                partial = raw

            sleep(sleep_time)
            elapsed += sleep_time

        return partial

    @staticmethod
    def __wait_for_job_items(driver: webdriver, tag: str, timeout=CONTAINER_WAIT_TIMEOUT) -> bool:
        '''
        Wait for the page to hold at least one job card

        The wait has to tolerate a full page load, not just a client side list update: the
        results are replaced from scratch, so for a while the page holds neither the old
        cards nor the new ones.

        :param driver: webdriver
        :param tag: str
        :param timeout: int
        :return: bool
        '''

        elapsed = 0
        sleep_time = 0.05  # 50 ms

        debug(tag, 'Waiting for new jobs to load')

        while elapsed < timeout:
            try:
                cards = driver.execute_script(
                    'return document.querySelectorAll(arguments[0]).length;',
                    Selectors.job_cards)
            except BaseException:
                # The document is replaced while the next page loads
                cards = None

            if cards:
                debug(tag, f'Next page rendered {cards} cards in {round(elapsed, 2)}s')
                return True

            sleep(sleep_time)
            elapsed += sleep_time

        return False

    def __paginate(self, driver: webdriver, url: str, tag: str) -> object:
        """
        Open the next page of results and wait for its list to be rendered

        :param driver: webdriver
        :param url: str the page to open, carrying its own `start` offset
        :param tag: str
        :return: object
        """

        def has_items(d: webdriver) -> bool:
            return AuthenticatedStrategy.__wait_for_job_items(d, tag)

        if self.__open_and_wait(driver, tag, url, has_items):
            return {'success': True}

        return {'success': False,
                'error': f'Timeout on pagination: no job card in '
                         f'{CONTAINER_WAIT_TIMEOUT}s. {AuthenticatedStrategy.__describe_page(driver)}'}

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

    @staticmethod
    def __resolve_apply_link(tag: str, driver: webdriver, details: JobDetails) -> str:
        '''
        The off-site application URL of an external job: the target of its apply anchor when
        it has one, otherwise the tab its apply button opens. Easy Apply has none.
        :param tag: str
        :param driver: webdriver
        :param details: JobDetails
        :return: str
        '''

        if details.is_easy_apply or details.apply_link:
            return details.apply_link

        apply_link_result = AuthenticatedStrategy.__extract_apply_link(tag, driver)
        return apply_link_result['apply_link'] if apply_link_result['success'] else ''

    @staticmethod
    def __wait_for_single_job(driver: WebDriver, job_id: str, timeout: float) -> SingleJobState | None:
        '''
        Wait for the single job page to settle on the job's details or on its "job not found"
        message
        :param driver: webdriver
        :param job_id: str
        :param timeout: seconds; 0 reads the page once
        :return: 'details', 'not-found', or None on timeout
        '''

        elapsed = 0
        sleep_time = 0.05

        while True:
            try:
                state = driver.execute_script(SINGLE_JOB_STATE_SCRIPT, job_id, JOB_NOT_FOUND_TEXT)
            except BaseException:
                state = None

            if state or elapsed >= timeout:
                return state

            sleep(sleep_time)
            elapsed += sleep_time

    def __start(self, driver: WebDriver, tag: str) -> bool:
        """
        Open LinkedIn and make sure the browser holds a session before any page that needs one

        :param driver: webdriver
        :param tag: str
        :return: bool False when the browser never landed on LinkedIn
        """

        # Open main page first to verify/set the session
        debug(tag, f'Opening {HOME_URL}')
        driver.get(HOME_URL)
        sleep(self.scraper.pacer.delay)

        # Both the masking and the cookies need the browser to be on a LinkedIn page: client
        # hints are not exposed outside a secure context, and a cookie can only be injected
        # for the domain of the document on screen
        if not wait_for_linkedin(driver):
            warn(tag, 'The browser never landed on LinkedIn, skip')
            debug(tag, AuthenticatedStrategy.__describe_page(driver))
            return False

        # This first page is the only one requested before the session cookie is in place,
        # so it is where the headless User-Agent can still be replaced without any
        # authenticated request having carried it
        mask_headless_user_agent(driver)

        has_profile = bool(self.scraper.chrome_user_data_dir)

        # A session already in the jar, which is what a persistent profile provides, wins
        # over any supplied credential. Only a profile can be carrying one, so only then is
        # it worth waiting for the navigation to deliver it.
        if has_profile:
            AuthenticatedStrategy.__wait_for_session(driver)

        if not AuthenticatedStrategy.__is_authenticated_session(driver):
            self.__require_session(driver, tag, has_profile)

        return True

    def resolve_location(self, driver: WebDriver, tag: str, name: str) -> PickedLocation | None:
        """
        Resolve a location name to LinkedIn's first suggestion for it, once per process

        The picker lives on the search page, so a search without a geoId is opened to reach it,
        which shows the location the account remembers. Nothing is submitted, so that location
        is left as it was.

        :param driver: webdriver
        :param tag: str
        :param name: str
        :return: PickedLocation, or None when LinkedIn has no suggestion for the name
        :raises LocationResolutionError: when the picker could not be operated or its page never
            rendered; nothing is cached then
        """

        cached, picked = LOCATION_CACHE.get(name)
        if cached:
            return picked

        if not self.__start(driver, tag):
            raise LocationResolutionError('The browser never landed on LinkedIn')

        url = f'{JOBS_SEARCH_RESULTS_URL}?' + urlencode({'keywords': 'jobs'})

        if not self.__open_and_wait(
                driver, tag, url,
                lambda d: AuthenticatedStrategy.__is_authenticated_session(d) and
                AuthenticatedStrategy.__wait_for_container(d)):
            debug(tag, AuthenticatedStrategy.__describe_page(driver))
            raise LocationResolutionError('The search page holding the location picker never rendered')

        try:
            picked = pick_location(driver, name)
        except (LocationPickerError, WebDriverException) as e:
            debug(tag, AuthenticatedStrategy.__describe_page(driver))
            raise LocationResolutionError(f'Could not operate the location picker for {name!r}: {e}') from e

        LOCATION_CACHE.put(name, picked)

        if picked is not None:
            info(tag, f'Location {name!r} resolved to {picked.label!r} (geoId {picked.geo_id})')

        return picked

    def scrape_job(self, driver: WebDriver, job_id: str, apply_link: bool = False) -> None:
        """
        Scrape a single job by its id

        The job's own /jobs/view/<id>/ page renders the same id-keyed detail components as
        the search panel, so that page is opened and its "About the job" component waited for.

        :param driver: webdriver
        :param job_id: str
        :param apply_link: bool
        :return: None
        """

        tag = f'[job:{job_id}]'

        if not self.__start(driver, tag):
            return

        has_profile = bool(self.scraper.chrome_user_data_dir)

        url = f'{JOBS_URL}/view/{job_id}/'

        # The page settles on either the job's detail components or its own "job not found"
        # message; anything else (a throttle that outlasted the backoff, a page that never
        # rendered) says nothing about whether the job exists
        if not self.__open_and_wait(
                driver, tag, url,
                lambda d: AuthenticatedStrategy.__wait_for_single_job(
                    d, job_id, SINGLE_JOB_PANEL_TIMEOUT) is not None):
            if AuthenticatedStrategy.__is_throttled(driver):
                # A 429 is transient: the job may well exist, we just could not confirm it
                warn(tag, f'LinkedIn kept throttling, could not confirm job {job_id}, skip')
                return

            warn(tag, f'The page did not load, nothing can be said about job {job_id}, skip')
            debug(tag, AuthenticatedStrategy.__describe_page(driver))
            return

        if AuthenticatedStrategy.__wait_for_single_job(driver, job_id, 0) == 'not-found':
            warn(tag, f'Job {job_id} not found or no longer available')
            self.scraper.emit(Events.NOT_FOUND, EventNotFound(job_id=job_id))
            return

        raw = AuthenticatedStrategy.__read_job_details(driver, job_id, SINGLE_JOB_PANEL_TIMEOUT)

        if raw is None:
            warn(tag, f'The details of job {job_id} did not render, skip')
            debug(tag, AuthenticatedStrategy.__describe_page(driver))
            return

        details = parse_job_details(raw, datetime.now())
        data = details.event_data()._replace(
            apply_link=AuthenticatedStrategy.__resolve_apply_link(tag, driver, details) if apply_link else '')

        info(tag, 'Processed')

        self.scraper.emit(Events.DATA, data)

    def run(
        self,
        driver: webdriver,
        search_url: str,
        query: Query,
        location: str,
        page_offset: int,
        expected_location: str = '',
    ) -> None:
        """
        Run strategy
        :param driver: webdriver
        :param cdp: CDP
        :param search_url: str
        :param query: Query
        :param location: str
        :param page_offset: int
        :param expected_location: str the location LinkedIn should apply, '' when not known; a
            search that applies another one is re-opened once, then skipped
        :return: None
        """

        tag = f'[{query.query}][{location}]'

        metrics = EventMetrics()

        pagination_index = page_offset

        if not self.__start(driver, tag):
            return

        has_profile = bool(self.scraper.chrome_user_data_dir)

        # Open search url
        current_url = override_query_params(search_url, {'start': pagination_index * PAGINATION_SIZE})

        if not self.__open_results(driver, tag, current_url, has_profile):
            return

        # LinkedIn can apply another location than the geoId asked for
        resolved_location = read_applied_location(driver)
        if expected_location and not location_matches(expected_location, resolved_location):
            warn(tag, f'LinkedIn applied location {resolved_location!r} instead of {expected_location!r}, '
                      're-opening the page')
            if not self.__open_results(driver, tag, current_url, has_profile):
                return
            resolved_location = read_applied_location(driver)
            if not location_matches(expected_location, resolved_location):
                warn(tag, f'LinkedIn applied location {resolved_location!r} again instead of '
                          f'{expected_location!r}, skip')
                return

        # A page is re-opened whenever the session has to be rebuilt part way through it, so
        # the jobs already delivered are remembered for the whole location rather than per
        # page. It also covers LinkedIn re-rendering a card it has already shown.
        processed_ids = set()
        recoveries = 0

        # Which document was on screen at the last reading, and how many refused requests it
        # had made by then. It is a local on purpose: one strategy instance serves every query
        # thread, so an attribute would be a race - and this reading belongs to a document,
        # where the pacer it feeds belongs to the account and is shared under a lock exactly
        # for that reason.
        throttled_resources = None

        # A limit of 0 means "scrape everything LinkedIn will serve": the loops run without a
        # processed count cap, stopping instead when a page yields no new job id or the
        # pagination ceiling is reached.
        limit = query.options.limit
        is_unlimited = limit == 0

        # BEGIN carries the total result count and must fire exactly once per location, so it
        # is guarded against the re-entry that a mid-run session recovery causes.
        begin_emitted = False

        # Pagination loop
        while is_unlimited or metrics.processed < limit:
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

            # Jobs are addressed by the id in each card's component key, never by their
            # position among the cards, which shifts whenever LinkedIn re-renders the list
            job_ids = AuthenticatedStrategy.__wait_for_stable_job_ids(driver)

            if not begin_emitted:
                begin_emitted = True
                self.__emit_begin(driver, tag, location, resolved_location)

            # LinkedIn serves the last page repeatedly once results run out, so in an
            # unlimited run a page carrying no id that has not already been processed marks
            # the end of the results and stops pagination.
            if is_unlimited and job_ids and all(job_id in processed_ids for job_id in job_ids):
                info(tag, 'No new jobs on this page, results exhausted')
                break

            next_index = 0
            session_lost = False

            # Jobs loop
            while (is_unlimited or metrics.processed < limit) and next_index < len(job_ids):
                job_index = next_index
                job_id = job_ids[job_index]
                next_index += 1

                if job_id in processed_ids:
                    debug(tag, f'Job {job_id} was already processed, skip')
                    continue

                sleep(self.scraper.pacer.delay)
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
                        # An id that left the list belongs to a render LinkedIn has since
                        # thrown away, so there is no job here to have failed
                        if load_card_result['missing']:
                            debug(tag, load_card_result['error'])
                            continue

                        error(tag, load_card_result['error'], exc_info=False)
                        info(tag, 'Failed to process')
                        metrics.failed += 1
                        continue

                    raw = driver.execute_script(
                        READ_JOB_CARD_SCRIPT, get_job_card_selector(job_id), job_id)

                    if not raw:
                        debug(tag, f'Job {job_id} is no longer in the results list')
                        continue

                    job = parse_job_record(raw)

                    # Promoted jobs
                    if query.options.skip_promoted_jobs and job.promoted:
                        info(tag, 'Skipped because promoted')
                        metrics.skipped += 1
                        continue

                    # Opening the card loads its detail panel, which is what LinkedIn fetches
                    # per job, and so what a throttle shows up on
                    driver.execute_script(
                        'const card = document.querySelector(arguments[0]); '
                        'if (card) { card.click(); }',
                        get_job_card_selector(job_id))

                    sleep(self.scraper.pacer.delay)

                    debug(tag, f'Loading details job {job_id}')
                    raw_details = AuthenticatedStrategy.__read_job_details(driver, job_id)

                    if raw_details is None:
                        error(tag, 'Timeout on loading job details', exc_info=False)
                        info(tag, 'Failed to process')
                        metrics.failed += 1
                        continue

                    details = parse_job_details(raw_details, datetime.now())
                    data = job.event_data(query=query.query, location=location,
                                          job_index=job_index, details=details)._replace(
                        resolved_location=resolved_location)

                    if query.options.apply_link:
                        data = data._replace(
                            apply_link=AuthenticatedStrategy.__resolve_apply_link(tag, driver, details))
                    else:
                        data = data._replace(apply_link='')

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
                finally:
                    # Every job reports once, however it ended: a page refusing to serve its
                    # details is exactly the throttle this is here to notice, and it leaves
                    # through the failure paths rather than the successful one
                    throttled_resources = self.__observe_resources(driver, tag, throttled_resources)

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
            if not is_unlimited and metrics.processed == limit:
                info(tag, 'Query limit reached!')
                self.__record_pace(metrics)
                info(tag, 'Metrics:', str(metrics))
                self.scraper.emit(Events.METRICS, metrics)
                break
            else:
                metrics.missed += len(job_ids) - next_index
                self.__record_pace(metrics)
                info(tag, 'Metrics:', str(metrics))
                self.scraper.emit(Events.METRICS, metrics)

            # Try to paginate
            pagination_index += 1

            # LinkedIn stops serving results past MAX_RESULTS_CEILING, so an unlimited run
            # does not advance start beyond it.
            if is_unlimited and pagination_index * PAGINATION_SIZE >= MAX_RESULTS_CEILING:
                info(tag, f'Reached the pagination ceiling of {MAX_RESULTS_CEILING} results, '
                          f'LinkedIn serves no more past it, stop')
                break

            info(tag, f'Pagination requested [{pagination_index}]')
            current_url = override_query_params(search_url, {'start': pagination_index * PAGINATION_SIZE})
            paginate_result = self.__paginate(driver, current_url, tag)

            # The next page does not always render on the first attempt, and giving up there
            # costs every result past the first page. A throttled one is the exception: the
            # backoff has already waited it out for as long as it is going to, so asking
            # again two seconds later only buys the same wait a second time.
            if not paginate_result['success'] and not AuthenticatedStrategy.__is_throttled(driver):
                warn(tag, 'Pagination failed, retrying', paginate_result['error'])
                sleep(PAGINATION_RETRY_DELAY)
                paginate_result = self.__paginate(driver, current_url, tag)

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
