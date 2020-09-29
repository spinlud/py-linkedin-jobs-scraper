import os
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from pyee import ExecutorEventEmitter
from urllib.parse import urlparse, urlencode, parse_qsl
from typing import Union, Callable, List
from selenium.webdriver.chrome.options import Options
from .utils.driver import build_chrome_driver
from .utils.logger import set_level, set_level_debug, set_level_info, set_level_warn, set_level_error
from .utils.logger import debug, info, warn, error
from .utils.url import get_query_params
from .query import Query, QueryOptions
from .constants import JOBS_SEARCH_URL
from .strategies import RunStrategy, LoggedOutRunStrategy, LoggedInRunStrategy
from .events import Events


class LinkedinScraper:
    def __init__(self, driver_builder: Callable = None, chrome_options: Options = None, max_workers: int = 2):
        self.driver_builder = driver_builder
        self.chrome_options = chrome_options
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._emitter = ExecutorEventEmitter(executor=self._pool)
        self._strategy: RunStrategy

        if 'LI_AT_COOKIE' in os.environ:
            info(f'Implementing strategy {LoggedInRunStrategy.__name__}')
            self._strategy = LoggedInRunStrategy(self)
        else:
            info(f'Implementing strategy {LoggedOutRunStrategy.__name__}')
            self._strategy = LoggedOutRunStrategy(self)

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

    def __run(self, query: Query) -> None:
        """
        Run query in a new thread
        :param query: Query
        :return: None
        """
        tid = threading.current_thread().ident
        tag = f'[T{tid}]'
        info(tag, 'Starting')

        if self.driver_builder is not None:
            driver = self.driver_builder()
        else:
            if self.chrome_options is not None:
                driver = build_chrome_driver(self.chrome_options)
            else:
                driver = build_chrome_driver()

        # Locations loop
        try:
            for location in query.options.locations:
                search_url = LinkedinScraper.__build_search_url(query, location)
                self._strategy.run(driver, search_url, query, location)
        except BaseException as e:
            error(tag, e, traceback.format_exc())
        finally:
            driver.quit()

        self.emit(Events.END.value)

    def run(self, queries: Union[Query, List[Query]], options: QueryOptions = None) -> None:
        if queries is None:
            raise ValueError('Parameter queries is missing')

        if not isinstance(queries, list):
            queries = [queries]

        # TODO Add validation

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

    def on(self, event: str, cb: Callable) -> None:
        self._emitter.on(event, cb)

    def emit(self, event: Events, *args):
        self._emitter.emit(event, *args)
