import traceback
from inspect import signature
from types import FunctionType
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urlencode
from typing import Union, Callable, List
from selenium.webdriver.chrome.options import Options
from .utils.logger import debug, info, warn, error
from .utils.url import get_query_params, get_domain
from .utils.chrome_driver import build_driver, get_websocket_debugger_url
from .utils.user_agent import get_random_user_agent
from .query import Query, QueryOptions
from .utils.constants import JOBS_SEARCH_URL
from .strategies import Strategy, AnonymousStrategy, AuthenticatedStrategy
from .config import Config
from .events import Events
from .chrome_cdp import CDP, CDPRequest, CDPResponse
from .exceptions import CallbackException, InvalidCookieException


class LinkedinScraper:
    """
    Args:
        chrome_options (selenium.webdriver.chrome.options.Options): Options to be passed to the Chrome driver.
            If None, default options will be used.
        max_workers (int): Number of threads spawned to execute concurrent queries. Each thread will use a
            different Chrome driver instance.
        slow_mo (float): Slow down the scraper execution, mainly to avoid 429 (Too many requests) errors.
    """

    def __init__(
            self,
            chrome_options: Options = None,
            max_workers: int = 2,
            slow_mo: float = 0.4):

        # Input validation
        if chrome_options is not None and not isinstance(chrome_options, Options):
            raise ValueError('Input parameter chrome_options must be instance of class '
                             'selenium.webdriver.chrome.options.Options')

        if not isinstance(max_workers, int) or max_workers < 1:
            raise ValueError('Input parameter max_workers must be a positive integer')

        if (not isinstance(slow_mo, int) and not isinstance(slow_mo, float)) or slow_mo < 0:
            raise ValueError('Input parameter slow_mo must be a positive number')

        self.chrome_options = chrome_options
        self.slow_mo = slow_mo
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._strategy: Strategy
        self._emitter = {
            Events.DATA: [],
            Events.ERROR: [],
            Events.INVALID_SESSION: [],
            Events.END: [],
        }

        if Config.LI_AT_COOKIE:
            info(f'Implementing strategy {AuthenticatedStrategy.__name__}')
            self._strategy = AuthenticatedStrategy(self)
        else:
            info(f'Implementing strategy {AnonymousStrategy.__name__}')
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
                params['f_TP' if not Config.LI_AT_COOKIE else 'f_TPR'] = query.options.filters.time.value
                debug(tag, 'Applied time filter', query.options.filters.time)

            if len(query.options.filters.type) > 0:
                filters = ','.join(e.value for e in query.options.filters.type)
                params['f_JT'] = filters
                debug(tag, 'Applied type filters', query.options.filters.type)

            if len(query.options.filters.experience) > 0:
                filters = ','.join(e.value for e in query.options.filters.experience)
                params['f_E'] = filters
                debug(tag, 'Applied experience filters', query.options.filters.experience)

        params['redirect'] = 'false'
        params['position'] = '1'
        params['pageNum'] = '0'

        parsed = parsed._replace(query=urlencode(params))
        return parsed.geturl()

    @staticmethod
    def __validate_run_input(queries: Union[Query, List[Query]], options: QueryOptions = None):
        """
        Validate run input parameters
        :param queries: Union[Query, List[Query]]
        :param options: QueryOptions
        :return: None
        """

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

    def __run(self, query: Query) -> None:
        """
        Run query in a new thread for each location
        :param query: Query
        :return: None
        """

        tag = f'[{query.query}]'
        driver = None
        devtools = None

        info('Starting new query', str(query))

        try:
            # Locations loop
            for location in query.options.locations:
                tag = f'[{query.query}][{location}]'
                search_url = LinkedinScraper.__build_search_url(query, location)

                driver = build_driver(options=self.chrome_options)
                websocket_debugger_url = get_websocket_debugger_url(driver)
                devtools = CDP(websocket_debugger_url)

                def on_request(request: CDPRequest) -> None:
                    domain = get_domain(request.url)

                    # By default blocks all tracking and 3rd part domains requests
                    if 'li/track' in request.url or domain not in {'linkedin.com', 'licdn.com'}:
                        return request.abort()

                    # If optimize is enabled, blocks other resource types
                    if query.options.optimize:
                        types_to_block = {
                            'image',
                            'stylesheet',
                            'media',
                            'font',
                            'texttrack',
                            'object',
                            'beacon',
                            'csp_report',
                            'imageset',
                        }

                        if request.resource_type.lower() in types_to_block:
                            return request.abort()

                    request.resume()

                def on_response(response: CDPResponse) -> None:
                    if response.status == 429:
                        warn(tag, '[429] Too many requests', 'You should probably increase scraper "slow_mo" value '
                                                             'or reduce concurrency')
                    elif response.status >= 400:
                        warn(tag, 'Error in response', str(response))

                # Add request/response listeners
                devtools.on('request', on_request)
                devtools.on('response', on_response)

                # Start devtools
                devtools.start()

                # Set random user agent
                devtools.set_user_agent(get_random_user_agent())

                # Run strategy
                self._strategy.run(driver, search_url, query, location)
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
                devtools.stop()
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
        LinkedinScraper.__validate_run_input(queries, options)

        # Merge with global options
        global_options = options if options is not None else QueryOptions(locations=['Worldwide'])
        for query in queries:
            if not isinstance(query, Query):
                raise ValueError('A query must be instance of class Query')
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

        if event == Events.DATA or event == Events.ERROR:
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
