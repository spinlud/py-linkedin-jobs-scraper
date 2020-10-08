import os
import traceback
import threading
from inspect import signature
from types import FunctionType
from concurrent.futures import ThreadPoolExecutor, wait
from urllib.parse import urlparse, urlencode, parse_qsl
from typing import Union, Callable, List
from selenium.webdriver.chrome.options import Options
from .utils.logger import set_level, set_level_debug, set_level_info, set_level_warn, set_level_error
from .utils.logger import debug, info, warn, error
from .utils.url import get_query_params, get_domain
from .utils.chrome_driver import build_driver, get_websocket_debugger_url
from .utils.user_agent import get_random_user_agent
from .query import Query, QueryOptions
from .constants import JOBS_SEARCH_URL
from .strategies import Strategy, AnonymousStrategy, AuthenticatedStrategy
from .events import Events
from .chrome_cdp import CDP, CDPRequest, CDPResponse


class LinkedinScraper:
    def __init__(
            self,
            chrome_options: Options = None,
            max_workers: int = 2,
            slow_mo: float = 0.1):

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
        self._events = set([e.value for e in Events])
        self._emitter = {
            Events.DATA.value: [],
            Events.ERROR.value: [],
            Events.END.value: [],
        }

        if 'LI_AT_COOKIE' in os.environ:
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

            if query.options.filters.relevance is not None:
                params['sortBy'] = query.options.filters.relevance.value

            if query.options.filters.time is not None:
                params['f_TP'] = query.options.filters.time.value

            if query.options.filters.type is not None:
                params['f_JT'] = query.options.filters.type.value

            if query.options.filters.experience is not None:
                params['f_E'] = query.options.filters.experience.value

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

        # Locations loop
        try:
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
        except BaseException as e:
            error(tag, e)
            self.emit(Events.ERROR.value, str(e) + '\n' + traceback.format_exc())
        finally:
            devtools.stop()
            debug(tag, 'Closing driver')
            driver.quit()

        # Emit END event
        self.emit(Events.END.value)

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

        for query in queries:
            print(query)

        futures = [self._pool.submit(self.__run, query) for query in queries]
        wait(futures)

    def on(self, event: str, cb: Callable, once=False) -> None:
        """
        Add callback for the given event
        :param event: str
        :param cb: Callable
        :param once: bool
        :return: None
        """

        if event not in self._events:
            raise ValueError(f'Event must be one of ({", ".join(self._events)})')

        if not isinstance(cb, FunctionType):
            raise ValueError('Callback must be a function')

        if event == Events.DATA.value or event == Events.ERROR.value:
            allowed_params = 1
        else:
            allowed_params = 0

        if len(signature(cb).parameters) != allowed_params:
            raise ValueError(f'Callback for event {event} must have {allowed_params} arguments')

        self._emitter[event].append({'cb': cb, 'once': once})

    def once(self, event: str, cb: Callable) -> None:
        """
        Add once callback for the given event
        :param event: str
        :param cb: Callable
        :return: None
        """

        self.on(event, cb, once=True)

    def emit(self, event: str, *args) -> None:
        """
        Execute callbacks for the given event
        :param event: str
        :param args: args
        :return: None
        """

        if event not in self._events:
            raise ValueError(f'Event must be one of ({", ".join(self._events)})')

        for listener in self._emitter[event]:
            listener['cb'](*args)

        # Remove 'once' callbacks
        self._emitter[event] = [e for e in self._emitter[event] if not e['once']]

    def remove_listener(self, event: str, cb: Callable) -> bool:
        """
        Remove listener for the given event
        :param event: str
        :param cb: Callable
        :return:
        """

        if event not in self._events:
            raise ValueError(f'Event must be one of ({", ".join(self._events)})')

        n = len(self._emitter[event])
        self._emitter[event] = [e for e in self._emitter[event] if e['cb'] != cb]
        return len(self._emitter[event]) < n

    def remove_all_listeners(self, event: str) -> None:
        """
        Remove all listeners for the given event
        :param event: str
        :return: None
        """

        if event not in self._events:
            raise ValueError(f'Event must be one of ({", ".join(self._events)})')

        self._emitter[event] = []
