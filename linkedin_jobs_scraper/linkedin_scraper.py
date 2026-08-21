import traceback
from inspect import signature
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urlencode
from typing import Union, Callable, List
from selenium.webdriver.chrome.options import Options
from .utils.logger import debug, info, warn, error
from .utils.url import get_query_params, get_domain, get_url_no_query_params, get_job_id
from .utils.chrome_driver import build_driver
from .utils.pacing import Pacer, MIN_SLOW_MO, PACING_CEILING_FACTOR, PACING_CEILING_LIMIT
from .utils.session import get_session_cookie, is_on_linkedin, wait_for_linkedin
from .login import ensure_session
from .query import Query, QueryOptions, Location
from .utils.constants import HOME_URL, JOBS_SEARCH_URL
from .strategies import Strategy, AuthenticatedStrategy
from .config import Config
from .events import Events, EventSession
from .exceptions import CallbackException, InvalidCookieException


class LinkedinScraper:
    """
    Args:
        chrome_options (selenium.webdriver.chrome.options.Options): Options to be passed to the Chrome driver.
            If None, default options will be used.
        headless (bool): Overrides headless mode only if chrome_options is None. If chrome_options is passed in
            the constructor, this flag is ignored.
        max_workers (int): Number of threads spawned to execute concurrent queries. Each thread will use a
            different Chrome driver instance. Forced to 1 when user_data_dir is set.
        slow_mo (float): Seconds slept between jobs, to avoid 429 (Too many requests) errors. It is the
            floor on that sleep, so the fastest the run will ever go rather than the pace it keeps:
            unless adaptive_slow_mo is off, a run that gets throttled paces itself above this number
            and eases back down towards it. Must be at least 0.2, the fastest any run is allowed to
            ask for.
        adaptive_slow_mo (bool): Let the run find its own pace between slow_mo and
            min(10, slow_mo * 10), doubling it on every 429 LinkedIn answers and easing it back after
            a run of jobs nobody refused. Off makes slow_mo a fixed delay again.
        page_load_timeout (int): Page load timeout.
        user_data_dir (str): Path to a Chrome profile directory kept across runs. The session it holds takes
            precedence over LI_AT_COOKIE, which makes the scraper survive a revoked cookie without any manual
            step. Only one live browser can use a profile at a time.
        interactive_login (bool): Sign in by hand into user_data_dir when it carries no reusable session,
            before the scrape starts. Requires user_data_dir, a display and somebody to type a password:
            it opens a visible browser and waits for it, so it is off by default and must stay off wherever
            nobody is watching, a CI job or a server.
    """

    def __init__(
            self,
            chrome_executable_path: str = None,
            chrome_binary_location: str = None,
            chrome_options: Options = None,
            headless: bool = True,
            max_workers: int = 2,
            slow_mo: float = 0.8,
            adaptive_slow_mo: bool = True,
            page_load_timeout=20,
            user_data_dir: str = None,
            interactive_login: bool = False):

        # Input validation
        if chrome_executable_path is not None and not isinstance(chrome_executable_path, str):
            raise ValueError('Input parameter chrome_executable_path must be of type str')

        if chrome_binary_location is not None and not isinstance(chrome_binary_location, str):
            raise ValueError('Input parameter chrome_binary_location must be of type str')

        if chrome_options is not None and not isinstance(chrome_options, Options):
            raise ValueError('Input parameter chrome_options must be instance of class '
                             'selenium.webdriver.chrome.options.Options')

        if not isinstance(max_workers, int) or max_workers < 1:
            raise ValueError('Input parameter max_workers must be a positive integer')

        if (not isinstance(slow_mo, int) and not isinstance(slow_mo, float)) or slow_mo < MIN_SLOW_MO:
            raise ValueError(f'Input parameter slow_mo must be a number of seconds no smaller than '
                             f'{MIN_SLOW_MO}: LinkedIn answers a run that asks for pages faster than '
                             f'that with HTTP 429, and no pacing can make up for it')

        if not isinstance(adaptive_slow_mo, bool):
            raise ValueError('Input parameter adaptive_slow_mo must be of type bool')

        if user_data_dir is not None and not isinstance(user_data_dir, str):
            raise ValueError('Input parameter user_data_dir must be of type str')

        if not isinstance(interactive_login, bool):
            raise ValueError('Input parameter interactive_login must be of type bool')

        if interactive_login and user_data_dir is None:
            raise ValueError('Input parameter interactive_login requires user_data_dir: signing in is only '
                             'worth doing into a profile that outlives the run')

        self.chrome_executable_path = chrome_executable_path
        self.chrome_binary_location = chrome_binary_location
        self.chrome_options = chrome_options
        self.headless = headless
        self.slow_mo = slow_mo
        self.adaptive_slow_mo = adaptive_slow_mo
        self.page_load_timeout = page_load_timeout
        self.user_data_dir = user_data_dir
        self.interactive_login = interactive_login

        # One pacer for the whole scraper, not one per query thread: LinkedIn enforces its
        # limit per account, so a refusal one worker meets is a reason for all of them to
        # slow down. It stays at slow_mo when the caller opted out of adapting.
        self.pacer = Pacer(
            floor=slow_mo,
            ceiling=min(PACING_CEILING_LIMIT, slow_mo * PACING_CEILING_FACTOR) if adaptive_slow_mo
            else slow_mo)

        if user_data_dir and max_workers > 1:
            warn('A Chrome profile cannot be shared by concurrent browsers, running one worker')
            max_workers = 1

        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._strategy: Strategy
        self._emitter = {
            Events.DATA: [],
            Events.ERROR: [],
            Events.METRICS: [],
            Events.BEGIN: [],
            Events.INVALID_SESSION: [],
            Events.SESSION_REFRESHED: [],
            Events.NOT_FOUND: [],
            Events.END: [],
        }

        # Every run authenticates, so there is one strategy and it is built unconditionally.
        # The constructor cannot tell whether a session will be available: a persistent profile
        # carries its own, and a caller can put --user-data-dir in their own chrome_options,
        # where no Config value describes the credential. So it warns about what it can see and
        # leaves the verdict to AuthenticatedStrategy.__authenticate, which says precisely what
        # is missing once a browser is open.
        if not (Config.LI_AT_COOKIE or Config.LI_RM_COOKIE or Config.LI_BCOOKIE or user_data_dir):
            warn('No credential configured: unless the browser brings a session of its own, there '
                 'will be nothing to scrape with. Set LI_RM_COOKIE with LI_BCOOKIE, or sign in '
                 'once with python -m linkedin_jobs_scraper.login --user-data-dir <path>')

        self._strategy = AuthenticatedStrategy(self)

    @staticmethod
    def __build_search_url(query: Query, location: Union[str, Location] = '') -> str:
        """
        Build jobs search url from query and location
        :param query: Query
        :param location: Union[str, Location]
        :return: str
        """

        # A Location pins the geo deterministically through geoId, in which case the location=
        # name param is omitted (LinkedIn lets geoId win over the name in a conflict). A plain
        # string sets location= as before.
        if isinstance(location, Location):
            location_tag = location.label
        else:
            location_tag = location

        tag = f'[{query.query}][{location_tag}]'
        parsed = urlparse(JOBS_SEARCH_URL)
        params = {}

        if len(query.query) > 0:
            params['keywords'] = query.query

        if isinstance(location, Location):
            params['geoId'] = location.geo_id
        elif len(location) > 0:
            params['location'] = location

        if query.options.filters is not None:
            if query.options.filters.company_jobs_url is not None:
                _params = get_query_params(query.options.filters.company_jobs_url)
                if 'f_C' in _params:
                    params['f_C'] = _params['f_C']
                    debug(tag, 'Applied company filter', query.options.filters.company_jobs_url)

            if query.options.filters.relevance is not None:
                params['sortBy'] = query.options.filters.relevance.value
                debug(tag, 'Applied relevance filter', query.options.filters.relevance)

            if query.options.filters.time is not None:
                params['f_TPR'] = query.options.filters.time.value
                debug(tag, 'Applied time filter', query.options.filters.time)

            if query.options.filters.base_salary is not None:
                params['f_SB2'] = query.options.filters.base_salary.value
                debug(tag, 'Applied base salary filter', query.options.filters.base_salary)

            if len(query.options.filters.type) > 0:
                filters = ','.join(e.value for e in query.options.filters.type)
                params['f_JT'] = filters
                debug(tag, 'Applied type filters', query.options.filters.type)

            if len(query.options.filters.experience) > 0:
                filters = ','.join(e.value for e in query.options.filters.experience)
                params['f_E'] = filters
                debug(tag, 'Applied experience filters', query.options.filters.experience)

            if len(query.options.filters.industry) > 0:
                filters = ','.join(e.value for e in query.options.filters.industry)
                params['f_I'] = filters
                debug(tag, 'Applied industry filters', query.options.filters.industry)

            if query.options.filters.on_site_or_remote is not None:
                filters = ','.join(e.value for e in query.options.filters.on_site_or_remote)
                params['f_WT'] = filters
                debug(tag, 'Applied on-site/remote filter', query.options.filters.on_site_or_remote)

            # Start offset
            params['start'] = '0'

        parsed = parsed._replace(query=urlencode(params))
        return parsed.geturl()

    def __emit_refreshed_session(self, driver) -> None:
        """
        Report the session cookie when it no longer matches the one supplied

        :param driver: webdriver
        :return: None
        """

        # The jar the driver exposes belongs to the page on screen, so a run that ended on an
        # error page reports no session at all - which is exactly the run whose caller most
        # needs the session that was issued along the way
        if not is_on_linkedin(driver):
            try:
                driver.get(HOME_URL)
            except BaseException:
                return

            if not wait_for_linkedin(driver):
                return

        li_at = get_session_cookie(driver)

        if li_at and li_at != Config.LI_AT_COOKIE:
            self.emit(Events.SESSION_REFRESHED, EventSession(li_at=li_at))

    def __run(self, query: Query) -> None:
        """
        Run query in a new thread for each location
        :param query: Query
        :return: None
        """

        tag = f'[{query.query}]'

        info('Starting new query', str(query))

        try:
            page_offset = query.options.page_offset

            driver = build_driver(
                executable_path=self.chrome_executable_path,
                binary_location=self.chrome_binary_location,
                options=self.chrome_options,
                headless=self.headless,
                user_data_dir=self.user_data_dir,
                timeout=self.page_load_timeout
            )

            # One browser serves every location of the query: each new browser means
            # another session establishment for LinkedIn to look at
            try:
                # Locations loop
                for location in query.options.locations:
                    # A location entry is a plain string or a Location; the strategy and
                    # EventData.location always receive the string label.
                    location_label = location.label if isinstance(location, Location) else location
                    tag = f'[{query.query}][{location_label}]'
                    search_url = LinkedinScraper.__build_search_url(query, location)

                    # Run strategy
                    self._strategy.run(
                        driver,
                        search_url,
                        query,
                        location_label,
                        page_offset,
                    )

                self.__emit_refreshed_session(driver)
            finally:
                try:
                    debug(tag, 'Closing driver')
                    driver.quit()
                except BaseException:
                    pass
        except CallbackException as e:
            error(tag, e)
            raise e
        except InvalidCookieException as e:
            error(tag, e)
            raise e
        except BaseException as e:
            error(tag, e)
            self.emit(Events.ERROR, str(e) + '\n' + traceback.format_exc())

        # Emit END event
        self.emit(Events.END)

    def scrape_job(self, url_or_id: str, apply_link: bool = False) -> None:
        """
        Scrape a single job by its url or id, bypassing search and pagination
        :param url_or_id: a numeric id, a '/jobs/view/<id>' url or a '?currentJobId=<id>' url
        :param apply_link: bool
        :return: None
        """

        job_id = get_job_id(url_or_id)
        tag = f'[job:{job_id}]'

        info('Starting single job scrape', job_id)

        # Chrome locks a profile directory, so the sign in has to be over before a browser
        # opens on it
        if self.interactive_login and not ensure_session(
                self.user_data_dir, self.chrome_executable_path, self.chrome_binary_location):
            raise RuntimeError('Interactive login did not establish a session, nothing to scrape with')

        try:
            driver = build_driver(
                executable_path=self.chrome_executable_path,
                binary_location=self.chrome_binary_location,
                options=self.chrome_options,
                headless=self.headless,
                user_data_dir=self.user_data_dir,
                timeout=self.page_load_timeout
            )

            try:
                self._strategy.scrape_job(driver, job_id, apply_link)
                self.__emit_refreshed_session(driver)
            finally:
                try:
                    debug(tag, 'Closing driver')
                    driver.quit()
                except BaseException:
                    pass
        except CallbackException as e:
            error(tag, e)
            raise e
        except InvalidCookieException as e:
            error(tag, e)
            raise e
        except BaseException as e:
            error(tag, e)
            self.emit(Events.ERROR, str(e) + '\n' + traceback.format_exc())

    def run(self, queries: Union[Query, List[Query]], options: QueryOptions = None) -> None:
        """
        Run a query or a list of queries
        :param queries: Union[Query, List[Query]]
        :param options: QueryOptions
        :return: None
        """

        # Validate input
        if queries is None:
            raise ValueError('Parameter queries is missing')

        if not isinstance(queries, list):
            queries = [queries]

        for query in queries:
            if not isinstance(query, Query):
                raise ValueError(f'A query object must be an instance of class Query, found {type(query)}')
            query.validate()

        if options is not None:
            if not isinstance(options, QueryOptions):
                raise ValueError(f'Parameter options must be an instance of class QueryOptions, found {type(options)}')
            options.validate()

        # Merge with global options
        global_options = options if options is not None \
            else QueryOptions(locations=['Worldwide'], limit=25)

        for query in queries:
            query.merge_options(global_options)

        # Chrome locks a profile directory, so the sign in has to be over before any worker
        # opens a browser on it
        if self.interactive_login and not ensure_session(
                self.user_data_dir, self.chrome_executable_path, self.chrome_binary_location):
            raise RuntimeError('Interactive login did not establish a session, nothing to scrape with')

        futures = [self._pool.submit(self.__run, query) for query in queries]
        [f.result() for f in futures]  # Necessary also to get exceptions from futures

    def on(self, event: Events, cb: Callable, once=False) -> None:
        """
        Add callback for the given event
        :param event: str
        :param cb: Callable
        :param once: bool
        :return: None
        """

        if not isinstance(event, Events):
            raise ValueError(f'Event must be an instance of enum class Events')

        if not callable(cb):
            raise ValueError('Callback must be callable')

        if event in (Events.DATA, Events.ERROR, Events.METRICS, Events.SESSION_REFRESHED, Events.BEGIN, Events.NOT_FOUND):
            allowed_params = 1
        else:
            allowed_params = 0

        if len(signature(cb).parameters) != allowed_params:
            raise ValueError(f'Callback for event {event} must have {allowed_params} arguments')

        self._emitter[event].append({'cb': cb, 'once': once})

    def once(self, event: Events, cb: Callable) -> None:
        """
        Add once callback for the given event
        :param event: str
        :param cb: Callable
        :return: None
        """

        self.on(event, cb, once=True)

    def emit(self, event: Events, *args) -> None:
        """
        Execute callbacks for the given event
        :param event: str
        :param args: args
        :return: None
        """

        if not isinstance(event, Events):
            raise ValueError(f'Event must be an instance of enum class Events')

        for listener in self._emitter[event]:
            try:
                listener['cb'](*args)
            except BaseException as e:
                raise CallbackException(str(e) + '\n' + traceback.format_exc())

        # Remove 'once' callbacks
        self._emitter[event] = [e for e in self._emitter[event] if not e['once']]

    def remove_listener(self, event: Events, cb: Callable) -> bool:
        """
        Remove listener for the given event
        :param event: str
        :param cb: Callable
        :return:
        """

        if not isinstance(event, Events):
            raise ValueError(f'Event must be an instance of enum class Events')

        n = len(self._emitter[event])
        self._emitter[event] = [e for e in self._emitter[event] if e['cb'] != cb]
        return len(self._emitter[event]) < n

    def remove_all_listeners(self, event: Events) -> None:
        """
        Remove all listeners for the given event
        :param event: str
        :return: None
        """

        if not isinstance(event, Events):
            raise ValueError(f'Event must be an instance of enum class Events')

        self._emitter[event] = []
