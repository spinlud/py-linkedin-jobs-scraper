import traceback
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from enum import Enum
from inspect import signature
from typing import TypeAlias, TypedDict
from urllib.parse import urlencode, urlparse

from selenium.webdriver.chrome.options import Options
from selenium.webdriver.remote.webdriver import WebDriver

from .config import Config
from .events import Events, EventSession
from .exceptions import (
    CallbackException,
    InvalidCookieException,
    LocationResolutionError,
    UnresolvedLocationError,
)
from .filters import EMPLOYMENT_TYPE_FACET, EXPERIENCE_FACET, WORKPLACE_FACET
from .login import ensure_session
from .query import Location, Query, QueryFilters, QueryOptions
from .strategies import AuthenticatedStrategy
from .utils.browser_errors import BROWSER_ERRORS
from .utils.chrome_driver import build_driver, quit_driver
from .utils.constants import HOME_URL, JOBS_SEARCH_RESULTS_URL
from .utils.location_picker import is_worldwide
from .utils.logger import debug, error, info, warn
from .utils.pacing import MIN_SLOW_MO, PACING_CEILING_FACTOR, PACING_CEILING_LIMIT, Pacer
from .utils.session import get_session_cookie, is_on_linkedin, wait_for_linkedin
from .utils.session_source import (
    SessionSource,
    has_cookie_credentials,
    is_empty_dir,
    missing_session_message,
    resolve_session_source,
)
from .utils.url import get_job_id, get_query_params

# The arity depends on the event, and is checked when a callback is registered
Callback: TypeAlias = Callable[..., object]  # type: ignore[explicit-any]  # no one signature


class Listener(TypedDict):
    cb: Callback
    once: bool


class LinkedinScraper:
    """
    Args:
        chrome_options (selenium.webdriver.chrome.options.Options): Options to be passed to the Chrome driver.
            If None, default options will be used.
        headless (bool): Overrides headless mode only if chrome_options is None. If chrome_options is passed in
            the constructor, this flag is ignored.
        max_workers (int): Number of threads spawned to execute concurrent queries, 1 by default. Each thread
            will use a different Chrome driver instance. Forced back to 1, with a warning, whenever the run uses
            a Chrome profile passed as chrome_user_data_dir or the default one.
        slow_mo (float): Seconds slept between jobs, to avoid 429 (Too many requests) errors. It is the
            floor on that sleep, so the fastest the run will ever go rather than the pace it keeps:
            unless adaptive_slow_mo is off, a run that gets throttled paces itself above this number
            and eases back down towards it. Must be at least 0.2, the fastest any run is allowed to
            ask for.
        adaptive_slow_mo (bool): Let the run find its own pace between slow_mo and
            min(10, slow_mo * 10), doubling it on every 429 LinkedIn answers and easing it back after
            a run of jobs nobody refused. Off makes slow_mo a fixed delay again.
        page_load_timeout (int): Page load timeout.
        chrome_user_data_dir (str): Path to a Chrome profile directory kept across runs; ~ is expanded. The
            session it holds takes precedence over LI_AT_COOKIE, which makes the scraper survive a revoked cookie
            without any manual step. Only one live browser can use a profile at a time. When it is None and the
            caller's chrome_options carry no --user-data-dir, the session comes from the cookies in the
            environment (LI_RM_COOKIE with LI_BCOOKIE, or LI_AT_COOKIE), or, when there are none, from the default
            profile ~/.lijs/chrome-profile (linkedin_jobs_scraper.login.sign_in creates it). A profile that is
            missing, empty or without a usable session makes the run emit INVALID_SESSION and raise
            InvalidCookieException; a missing or empty one does so before any browser opens.
        interactive_login (bool): Sign in by hand into the Chrome profile when it carries no reusable session,
            before the scrape starts. Requires the run to use a profile, chrome_user_data_dir or the default one,
            a display and somebody to type a password: it opens a visible browser and waits for it, so it is off
            by default and must stay off wherever nobody is watching, a CI job or a server.
    """

    def __init__(
        self,
        chrome_executable_path: str | None = None,
        chrome_binary_location: str | None = None,
        chrome_options: Options | None = None,
        headless: bool = True,
        max_workers: int = 1,
        slow_mo: float = 0.8,
        adaptive_slow_mo: bool = True,
        page_load_timeout: float = 20,
        chrome_user_data_dir: str | None = None,
        interactive_login: bool = False,
    ):

        # Input validation
        if chrome_executable_path is not None and not isinstance(chrome_executable_path, str):
            raise ValueError('Input parameter chrome_executable_path must be of type str')

        if chrome_binary_location is not None and not isinstance(chrome_binary_location, str):
            raise ValueError('Input parameter chrome_binary_location must be of type str')

        if chrome_options is not None and not isinstance(chrome_options, Options):
            raise ValueError(
                'Input parameter chrome_options must be instance of class '
                'selenium.webdriver.chrome.options.Options'
            )

        if not isinstance(max_workers, int) or max_workers < 1:
            raise ValueError('Input parameter max_workers must be a positive integer')

        if (
            not isinstance(slow_mo, int) and not isinstance(slow_mo, float)
        ) or slow_mo < MIN_SLOW_MO:
            raise ValueError(
                f'Input parameter slow_mo must be a number of seconds no smaller than '
                f'{MIN_SLOW_MO}: LinkedIn answers a run that asks for pages faster than '
                f'that with HTTP 429, and no pacing can make up for it'
            )

        if not isinstance(adaptive_slow_mo, bool):
            raise ValueError('Input parameter adaptive_slow_mo must be of type bool')

        if chrome_user_data_dir is not None and not isinstance(chrome_user_data_dir, str):
            raise ValueError('Input parameter chrome_user_data_dir must be of type str')

        if not isinstance(interactive_login, bool):
            raise ValueError('Input parameter interactive_login must be of type bool')

        session_source = resolve_session_source(chrome_user_data_dir, chrome_options)

        if interactive_login and not session_source.is_persistent_profile:
            raise ValueError(
                'Input parameter interactive_login requires a Chrome profile, chrome_user_data_dir or '
                'the default one used when no cookie is set in the environment: signing in is only '
                'worth doing into a profile that outlives the run'
            )

        self.chrome_executable_path = chrome_executable_path
        self.chrome_binary_location = chrome_binary_location
        self.chrome_options = chrome_options
        self.headless = headless
        self.slow_mo = slow_mo
        self.adaptive_slow_mo = adaptive_slow_mo
        self.page_load_timeout = page_load_timeout
        self.session_source: SessionSource = session_source
        self.chrome_user_data_dir: str | None = (
            str(session_source.chrome_user_data_dir)
            if session_source.chrome_user_data_dir is not None
            else None
        )
        self.interactive_login = interactive_login

        # One pacer for the whole scraper, not one per query thread: LinkedIn enforces its
        # limit per account, so a refusal one worker meets is a reason for all of them to
        # slow down. It stays at slow_mo when the caller opted out of adapting.
        self.pacer = Pacer(
            floor=slow_mo,
            ceiling=min(PACING_CEILING_LIMIT, slow_mo * PACING_CEILING_FACTOR)
            if adaptive_slow_mo
            else slow_mo,
        )

        if self.chrome_user_data_dir and max_workers > 1:
            warn('A Chrome profile cannot be shared by concurrent browsers, running one worker')
            max_workers = 1

        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._emitter: dict[Events, list[Listener]] = {
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
        # Whether the chosen source actually holds a session is only known once a browser is
        # open, which is where AuthenticatedStrategy._authenticate says what is missing.
        self._strategy = AuthenticatedStrategy(self)

    @staticmethod
    def _workplace_hint(location: str) -> str:
        """
        A pointer to the workplace filter for 'Remote', which LinkedIn's location picker
        does not know because remote work is a workplace type, not a place.
        """
        if location.strip().lower() != 'remote':
            return ''
        return (
            '; remote work is a workplace type, not a place: use the filter '
            'OnSiteOrRemoteFilters.REMOTE (--workplace remote in the CLI)'
        )

    @staticmethod
    def _geo_id(location: str | Location) -> str | None:
        """
        The geoId a location stands for: a Location's own, a numeric string as is, and None
        for no location, which leaves the location the account remembers applied. LinkedIn
        drops a free-text location= parameter, so a name it cannot be turned into a geoId
        is refused rather than searched without one.
        """
        if isinstance(location, Location):
            return location.geo_id

        name = location.strip()
        if name == '':
            return None
        if name.isdigit():
            return name

        raise UnresolvedLocationError(f'Location {name!r} is not a LinkedIn geoId')

    @staticmethod
    def _f_sal(filters: QueryFilters) -> str:
        """
        The f_SAL parameter: one section per facet with a selection, values comma-separated
        within a section and sections joined with '$' (workplace, experience, employment type)
        """
        sections: list[tuple[str, Sequence[Enum]]] = [
            (WORKPLACE_FACET, filters.on_site_or_remote),
            (EXPERIENCE_FACET, filters.experience),
            (EMPLOYMENT_TYPE_FACET, filters.type),
        ]
        return '$'.join(
            f'f_SA_id_{facet}:' + ','.join(e.value for e in values)
            for facet, values in sections
            if len(values) > 0
        )

    @staticmethod
    def _build_search_url(query: Query, location: str | Location = '') -> str:
        """
        Build jobs search url from query and location
        :param query: Query
        :param location: Union[str, Location]
        :return: str
        """

        if isinstance(location, Location):
            location_tag = location.label
        else:
            location_tag = location

        tag = f'[{query.query}][{location_tag}]'
        parsed = urlparse(JOBS_SEARCH_RESULTS_URL)
        params = {}

        if len(query.query) > 0:
            params['keywords'] = query.query

        geo_id = LinkedinScraper._geo_id(location)
        if geo_id is not None:
            params['geoId'] = geo_id

        filters = query.options.filters
        if filters is not None:
            if filters.company_jobs_url is not None:
                _params = get_query_params(filters.company_jobs_url)
                if 'f_C' in _params:
                    params['f_C'] = _params['f_C']
                    debug(tag, 'Applied company filter', filters.company_jobs_url)

            if filters.company_id is not None:
                params['f_C'] = filters.company_id
                debug(tag, 'Applied company filter', filters.company_id)

            if filters.time is not None:
                params['f_TPR'] = filters.time.value
                debug(tag, 'Applied time filter', filters.time)

            f_sal = LinkedinScraper._f_sal(filters)
            if f_sal:
                params['f_SAL'] = f_sal
                debug(tag, 'Applied f_SAL filters', f_sal)

            if filters.easy_apply:
                params['f_AL'] = 'true'
                debug(tag, 'Applied easy apply filter')

            if filters.under_10_applicants:
                params['f_EA'] = 'true'
                debug(tag, 'Applied under 10 applicants filter')

            if filters.verified:
                params['f_VJ'] = 'true'
                debug(tag, 'Applied verified filter')

        # Start offset
        params['start'] = '0'

        parsed = parsed._replace(query=urlencode(params))
        return parsed.geturl()

    def _emit_refreshed_session(self, driver: WebDriver) -> None:
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
            except BROWSER_ERRORS:
                return

            if not wait_for_linkedin(driver):
                return

        li_at = get_session_cookie(driver)

        if li_at and li_at != Config.LI_AT_COOKIE:
            self.emit(Events.SESSION_REFRESHED, EventSession(li_at=li_at))

    def _prepare_session(self) -> None:
        """
        Report the session source and make sure it can be used, before any browser opens

        Chrome locks a profile directory, so an interactive sign in has to be over before a
        browser opens on it. A profile that is missing or empty holds no session, and with no
        cookie in the environment to seed it there is nothing to authenticate with: the run
        stops here, the way a profile without a usable session stops once a browser has
        looked at it - INVALID_SESSION, then InvalidCookieException - rather than have Chrome
        create an empty profile and fail later and less clearly. The profile is never created
        here.

        :return: None
        """

        info(self.session_source.describe())

        if self.interactive_login and not ensure_session(
            self.chrome_user_data_dir, self.chrome_executable_path, self.chrome_binary_location
        ):
            raise RuntimeError(
                'Interactive login did not establish a session, nothing to scrape with'
            )

        profile = self.session_source.chrome_user_data_dir
        if (
            self.session_source.is_persistent_profile
            and profile is not None
            and not has_cookie_credentials()
            and (not profile.is_dir() or is_empty_dir(profile))
        ):
            self.emit(Events.INVALID_SESSION)
            raise InvalidCookieException(missing_session_message(profile))

    @contextmanager
    def _browser(self, tag: str) -> Iterator[WebDriver]:
        """
        Open a browser, and close it however its use ends
        :param tag: str
        :return: the browser's driver
        """

        driver = build_driver(
            executable_path=self.chrome_executable_path,
            binary_location=self.chrome_binary_location,
            options=self.chrome_options,
            headless=self.headless,
            chrome_user_data_dir=self.chrome_user_data_dir,
            timeout=self.page_load_timeout,
        )

        try:
            yield driver
        finally:
            debug(tag, 'Closing driver')
            quit_driver(driver)

    @contextmanager
    def _failures_reported(self, tag: str) -> Iterator[None]:
        """
        Turn a failure into an ERROR event, except for those meant for the caller
        :param tag: str
        :return: None
        """

        try:
            yield
        except (CallbackException, InvalidCookieException) as e:
            error(tag, e)
            raise
        # ruff: ignore[BLE001] whatever else a query or a single job fails on is an ERROR event
        except Exception as e:
            error(tag, e)
            self.emit(Events.ERROR, str(e) + '\n' + traceback.format_exc())

    def _run(self, query: Query) -> None:
        """
        Run query in a new thread for each location
        :param query: Query
        :return: None
        """

        tag = f'[{query.query}]'

        info('Starting new query', str(query))

        with self._failures_reported(tag), self._browser(tag) as driver:
            # One browser serves every location of the query: each new browser means
            # another session establishment for LinkedIn to look at
            locations, page_offset = query.options.locations, query.options.page_offset
            # Query.merge_options gives them a value
            assert locations is not None
            assert page_offset is not None
            for location in locations:
                # A location entry is a plain string or a Location; the strategy and
                # EventData.location always receive the string label.
                location_label = location.label if isinstance(location, Location) else location
                tag = f'[{query.query}][{location_label}]'
                if isinstance(location, str) and is_worldwide(location):
                    warn(
                        tag,
                        f"Location {location!r} skipped: LinkedIn's search no longer offers a "
                        "worldwide search; omit the location to use the account's current location",
                    )
                    continue
                # The name LinkedIn should show as applied, known only for a name the picker resolved
                expected_location = ''
                try:
                    search_url = LinkedinScraper._build_search_url(query, location)
                except UnresolvedLocationError:
                    assert isinstance(location, str)  # a Location carries its geoId
                    # A name is turned into a geoId through the page's location picker
                    try:
                        picked = self._strategy.resolve_location(driver, tag, location)
                    except LocationResolutionError as e:
                        warn(tag, f'Could not resolve location {location!r}, skip', e)
                        continue
                    if picked is None:
                        warn(
                            tag,
                            f'Location {location!r} matches no LinkedIn location, skip'
                            + LinkedinScraper._workplace_hint(location),
                        )
                        continue
                    search_url = LinkedinScraper._build_search_url(
                        query, Location(geo_id=picked.geo_id, name=location)
                    )
                    expected_location = picked.label

                # Run strategy
                self._strategy.run(
                    driver,
                    search_url,
                    query,
                    location_label,
                    page_offset,
                    expected_location,
                )

            self._emit_refreshed_session(driver)

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

        self._prepare_session()

        with self._failures_reported(tag), self._browser(tag) as driver:
            self._strategy.scrape_job(driver, job_id, apply_link)
            self._emit_refreshed_session(driver)

    def run(self, queries: Query | list[Query], options: QueryOptions | None = None) -> None:
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
                raise ValueError(
                    f'A query object must be an instance of class Query, found {type(query)}'
                )
            query.validate()

        if options is not None:
            if not isinstance(options, QueryOptions):
                raise ValueError(
                    f'Parameter options must be an instance of class QueryOptions, found {type(options)}'
                )
            options.validate()

        # Merge with global options
        global_options = options if options is not None else QueryOptions()

        for query in queries:
            query.merge_options(global_options)

        self._prepare_session()

        futures = [self._pool.submit(self._run, query) for query in queries]
        [f.result() for f in futures]  # Necessary also to get exceptions from futures

    def on(self, event: Events, cb: Callback, once: bool = False) -> None:
        """
        Add callback for the given event
        :param event: str
        :param cb: Callable
        :param once: bool
        :return: None
        """

        if not isinstance(event, Events):
            raise ValueError('Event must be an instance of enum class Events')

        if not callable(cb):
            raise ValueError('Callback must be callable')

        if event in (
            Events.DATA,
            Events.ERROR,
            Events.METRICS,
            Events.SESSION_REFRESHED,
            Events.BEGIN,
            Events.NOT_FOUND,
        ):
            allowed_params = 1
        else:
            allowed_params = 0

        if len(signature(cb).parameters) != allowed_params:
            raise ValueError(f'Callback for event {event} must have {allowed_params} arguments')

        self._emitter[event].append({'cb': cb, 'once': once})

    def once(self, event: Events, cb: Callback) -> None:
        """
        Add once callback for the given event
        :param event: str
        :param cb: Callable
        :return: None
        """

        self.on(event, cb, once=True)

    def emit(self, event: Events, *args: object) -> None:
        """
        Execute callbacks for the given event
        :param event: str
        :param args: args
        :return: None
        """

        if not isinstance(event, Events):
            raise ValueError('Event must be an instance of enum class Events')

        for listener in self._emitter[event]:
            try:
                listener['cb'](*args)
            except Exception as e:
                # Whatever a callback raises is the caller's own failure
                raise CallbackException(str(e) + '\n' + traceback.format_exc()) from e

        # Remove 'once' callbacks
        self._emitter[event] = [e for e in self._emitter[event] if not e['once']]

    def remove_listener(self, event: Events, cb: Callback) -> bool:
        """
        Remove listener for the given event
        :param event: str
        :param cb: Callable
        :return:
        """

        if not isinstance(event, Events):
            raise ValueError('Event must be an instance of enum class Events')

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
            raise ValueError('Event must be an instance of enum class Events')

        self._emitter[event] = []
