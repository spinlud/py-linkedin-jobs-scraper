import traceback
from selenium import webdriver
from ..utils.logger import debug, info, warn, error
from ..query import Query
from ..utils.user_agent import get_random_user_agent
from ..utils.url import get_domain
from ..utils.chrome_driver import build_driver, get_websocket_debugger_url
from ..chrome_cdp import CDP, CDPRequest, CDPResponse
from ..events import Events


class Strategy:
    def __init__(self, scraper: 'LinkedinScraper'):
        self.scraper = scraper

    def run(self, search_url: str, query: Query, location: str) -> None:
        tag = f'[{query.query}][{location}]'
        driver = None
        devtools = None

        try:
            driver = build_driver(options=self.scraper.chrome_options)
            websocket_debugger_url = get_websocket_debugger_url(driver)
            devtools = CDP(websocket_debugger_url)

            def on_request(request: CDPRequest) -> None:
                domain = get_domain(request.url)

                # By default blocks all tracking and 3rd part domains requests
                if 'li/track' in request.url or domain not in {'linkedin.com', 'licdn.com'}:
                    return request.abort()

                # If optimize is enabled, blocks other resource types
                if self.scraper.optimize:
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
            self.run_strategy(driver, search_url, query, location)
        except BaseException as e:
            error(tag, e)
            self.scraper.emit(Events.ERROR.value, str(e) + '\n' + traceback.format_exc())
        finally:
            devtools.stop()
            debug(tag, 'Closing driver')
            driver.quit()

    def run_strategy(self, driver: webdriver, search_url: str, query: Query, location: str) -> None:
        raise NotImplementedError('Must implement method in subclass')
