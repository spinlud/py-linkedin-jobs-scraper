import traceback
import requests
from inspect import signature
from types import FunctionType
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urlencode
from typing import Union, Callable, List
from selenium.webdriver.chrome.options import Options
from .utils.logger import debug, info, warn, error
from .utils.url import get_query_params, get_domain, get_url_no_query_params
from .utils.chrome_driver import build_driver, get_websocket_debugger_url
from .utils.user_agent import get_random_user_agent
from .query import Query, QueryOptions
from .utils.constants import JOBS_SEARCH_URL
from .strategies import Strategy, AnonymousStrategy, AuthenticatedStrategy
from .config import Config
from .events import Events
from .chrome_cdp import CDP, CDPRequest, CDPResponse, CDPCookie
from .exceptions import CallbackException, InvalidCookieException


class LinkedinScraper:
    """
    Args:
        chrome_options (selenium.webdriver.chrome.options.Options): Options to be passed to the Chrome driver.
            If None, default options will be used.
        headless (bool): Overrides headless mode only if chrome_options is None. If chrome_options is passed in
            the constructor, this flag is ignored.
        max_workers (int): Number of threads spawned to execute concurrent queries. Each thread will use a
            different Chrome driver instance.
        slow_mo (float): Slow down the scraper execution, mainly to avoid 429 (Too many requests) errors.
        page_load_timeout (int): Page load timeout.
    """

    def __init__(
            self,
            chrome_executable_path = None,
            chrome_options: Options = None,
            headless: bool = True,
            proxies: List[str] = None,
            max_workers: int = 2,
            slow_mo: float = 0.5,
            page_load_timeout=20):

        # Input validation
        if chrome_executable_path is not None and not isinstance(chrome_executable_path, str):
            raise ValueError('Input parameter chrome_executable_path must be of type str')

        if chrome_options is not None and not isinstance(chrome_options, Options):
            raise ValueError('Input parameter chrome_options must be instance of class '
                             'selenium.webdriver.chrome.options.Options')

        if not isinstance(max_workers, int) or max_workers < 1:
            raise ValueError('Input parameter max_workers must be a positive integer')

        if (not isinstance(slow_mo, int) and not isinstance(slow_mo, float)) or slow_mo < 0:
            raise ValueError('Input parameter slow_mo must be a positive number')

        self.chrome_executable_path = chrome_executable_path
        self.chrome_options = chrome_options
        self.headless = headless
        self.slow_mo = slow_mo
        self.page_load_timeout = page_load_timeout

        self._proxies = proxies if proxies else []
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._strategy: Strategy
        self._emitter = {
            Events.DATA: [],
            Events.ERROR: [],
            Events.METRICS: [],
            Events.INVALID_SESSION: [],
            Events.END: [],
        }

        if Config.LI_AT_COOKIE:
            info(f'Using strategy {AuthenticatedStrategy.__name__}')
            self._strategy = AuthenticatedStrategy(self)

            if proxies:
                warn(f'Proxy mode is currently not supported in {AuthenticatedStrategy.__name__}')
        else:
            info(f'Using strategy {AnonymousStrategy.__name__}')
            self._strategy = AnonymousStrategy(self)

    @staticmethod
    def __build_search_url(query: Query, location: str = '') -> str:
        """
        Build jobs search url from query and location
        :param query: Query
        :param location: str
        :return: str
        """

        tag = f'[{query.query}][{location}]'
        parsed = urlparse(JOBS_SEARCH_URL)
        params = {}

        if len(query.query) > 0:
            params['keywords'] = query.query

        if len(location) > 0:
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

            if len(query.options.filters.type) > 0:
                filters = ','.join(e.value for e in query.options.filters.type)
                params['f_JT'] = filters
                debug(tag, 'Applied type filters', query.options.filters.type)

            if len(query.options.filters.experience) > 0:
                filters = ','.join(e.value for e in query.options.filters.experience)
                params['f_E'] = filters
                debug(tag, 'Applied experience filters', query.options.filters.experience)

            # On site/remote filters supported only with authenticated session (for now)
            if query.options.filters.on_site_or_remote is not None and Config.LI_AT_COOKIE:
                filters = ','.join(e.value for e in query.options.filters.on_site_or_remote)
                params['f_WT'] = filters
                debug(tag, 'Applied on-site/remote filter', query.options.filters.on_site_or_remote)

            # Start offset
            params['start'] = '0'

        parsed = parsed._replace(query=urlencode(params))
        return parsed.geturl()

    def __run(self, query: Query) -> None:
        """
        Run query in a new thread for each location
        :param query: Query
        :return: None
        """

        tag = f'[{query.query}]'
        driver = None
        cdp = None

        info('Starting new query', str(query))

        if query.options.optimize:
            warn('Query option optimize=True: this could cause issues in jobs loading or pagination')

        try:
            # Locations loop
            for location in query.options.locations:
                tag = f'[{query.query}][{location}]'
                search_url = LinkedinScraper.__build_search_url(query, location)

                driver = build_driver(
                    executable_path=self.chrome_executable_path,
                    options=self.chrome_options,
                    headless=self.headless,
                    timeout=self.page_load_timeout
                )

                websocket_debugger_url = get_websocket_debugger_url(driver)
                cdp = CDP(websocket_debugger_url)
                session = requests.Session()
                proxy_index = 0

                def on_request(request: CDPRequest) -> None:
                    domain = get_domain(request.url)

                    # Block tracking and other stuff not useful
                    to_block = [
                        'li/track',
                        'realtime.www.linkedin.com/realtime',
                        'platform.linkedin.com/litms/utag/voyager-web-jobs',
                    ]

                    if any([e in request.url for e in to_block]):
                        return request.abort()

                    # Block 3rd part domains requests
                    if domain not in {'linkedin.com', 'licdn.com'}:
                        return request.abort()

                    # If optimize is enabled, block other resource types
                    if query.options.optimize:
                        types_to_block = {
                            'image',
                            'stylesheet',
                            'media',
                            'font',
                            'imageset',
                        }

                        if request.resource_type.lower() in types_to_block:
                            return request.abort()

                    # TODO: rotating proxy mode, only "working" in anonymous mode (discontinued)
                    if len(self._proxies) > 0 and not Config.LI_AT_COOKIE:
                        # Do not proxy request with non http(s) scheme
                        if 'http' not in urlparse(request.url).scheme.lower():
                            return request.resume()

                        # Always got 400 on proxying these requests, reason still unknown...
                        if 'api/ingraphs' in request.url:
                            return request.resume()

                        nonlocal session
                        nonlocal proxy_index

                        # Rotate proxy
                        proxy = self._proxies[proxy_index % len(self._proxies)]
                        proxy_index += 1

                        # Try proxying the request
                        debug(f'Proxying request to {proxy}', request.url, request.method)
                        try:
                            response = session.request(
                                url=request.url,
                                method=request.method,
                                headers=request.headers,
                                data=request.post_data,
                                cookies=session.cookies,
                                verify=False,
                                proxies={
                                    'http': proxy,
                                    'https': proxy,
                                },
                            )
                        # Resume request in case of a proxy error
                        except requests.exceptions.ProxyError as e:
                            warn(e)
                            return request.resume()

                        cdp_cookies = []

                        for cookie in session.cookies:
                            cdp_cookies.append(CDPCookie(
                                name=cookie.name,
                                value=cookie.value,
                                domain=cookie.domain,
                                secure=cookie.secure,
                                expires=cookie.expires,
                            ))

                        # Set cookies from request session to browser
                        cdp.set_cookies(cdp_cookies)

                        try:
                            return request.fulfill(
                                code=response.status_code,
                                headers=response.headers,
                                body=response.content,
                            )
                        except Exception as e:
                            print(e)
                            return request.resume()
                    # Non-proxy mode
                    else:
                        return request.resume()

                def on_response(response: CDPResponse) -> None:
                    if response.status == 429:
                        warn(tag, '[429] Too many requests', 'You should probably increase scraper "slow_mo" value '
                                                             'or reduce concurrency')
                    elif response.status >= 400:
                        warn(tag, 'Error in response', driver.current_url, str(response))

                # Add request/response listeners
                cdp.on('request', on_request)
                cdp.on('response', on_response)

                # Start devtools
                cdp.start()

                # Enable Content Security Policy bypass: needed for pagination to work properly in anonymous mode
                cdp.set_bypass_csp(True)

                # Set random user agent
                cdp.set_user_agent(get_random_user_agent())

                # Run strategy
                self._strategy.run(
                    driver,
                    cdp,
                    search_url,
                    query,
                    location,
                    # query.options.apply_link
                )

                try:
                    debug(tag, 'Stopping Chrome DevTools')
                    cdp.stop()
                except:
                    pass

                try:
                    debug(tag, 'Closing driver active window')
                    driver.close()
                except:
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
        finally:
            try:
                debug(tag, 'Stopping Chrome DevTools')
                cdp.stop()
            except:
                pass

            try:
                debug(tag, 'Closing driver')
                driver.quit()
            except:
                pass

        # Emit END event
        self.emit(Events.END)

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
            else QueryOptions(locations=['Worldwide'], limit=25, optimize=False)

        for query in queries:
            query.merge_options(global_options)

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

        if not isinstance(cb, FunctionType):
            raise ValueError('Callback must be a function')

        if event == Events.DATA or event == Events.ERROR or event == Events.METRICS:
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

    def get_proxies(self):
        """
        Get proxies
        :return: List[str]
        """

        return self._proxies

    def set_proxies(self, proxies: List[str]):
        """
        Set proxies
        :param proxies:
        :return: None
        """

        self._proxies = proxies

    def add_proxy(self, proxy: str):
        """
        Add a proxy
        :param proxy:
        :return: None
        """

        self._proxies.append(proxy)

    def remove_proxy(self, proxy: str):
        """
        Remove a proxy
        :param proxy:
        :return: None
        """

        self._proxies = list(filter(lambda e: e != proxy, self._proxies))
