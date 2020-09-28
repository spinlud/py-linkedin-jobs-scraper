import threading
from concurrent.futures import ThreadPoolExecutor, wait
from pyee import ExecutorEventEmitter
from typing import Callable
from .utils.chrome_utils import build_default_chrome_driver
from .logger import debug, info, warn, error


class LinkedinScraper:
    def __init__(self, chrome_options=None, max_workers=2):
        self.chrome_options = chrome_options
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._emitter = ExecutorEventEmitter(executor=self._pool)

    def __run(self, url):
        tid = threading.current_thread().ident
        tag = f'[{tid}]'
        info(tag, 'Starting')

        driver = build_default_chrome_driver()

        info(tag, 'Opening url', url)
        driver.get(url)

        res = len(driver.page_source)

        self._emitter.emit('data', f'{tag} {res}')

        try:
            driver.quit()
        except BaseException as e:
            error('ERROR', e)
            return 'ERROR'

    def run(self, urls):
        futures = [self._pool.submit(self.__run, url) for url in urls]
        wait(futures)

    def on(self, event: str, cb: Callable) -> None:
        self._emitter.on(event, cb)
