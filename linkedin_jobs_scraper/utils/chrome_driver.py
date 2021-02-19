import urllib3
import json
from selenium import webdriver
from selenium.webdriver.common.proxy import Proxy, ProxyType
from selenium.webdriver.chrome.options import Options
from linkedin_jobs_scraper.utils.logger import debug


def get_default_driver_options(width=1472, height=828, headless=True) -> Options:
    """
    Generate default Chrome driver options
    :param width: int
    :param height: int
    :param headless: bool
    :return: Options
    """

    chrome_options = Options()
    chrome_options.headless = headless
    chrome_options.page_load_strategy = 'normal'

    chrome_options.add_argument("--enable-automation"),
    chrome_options.add_argument("--start-maximized"),
    chrome_options.add_argument(f"--window-size={width},{height}"),
    chrome_options.add_argument("--lang=en-GB"),
    chrome_options.add_argument("--no-sandbox"),
    chrome_options.add_argument("--disable-setuid-sandbox"),
    chrome_options.add_argument("--disable-dev-shm-usage"),
    chrome_options.add_argument("--disable-gpu"),
    chrome_options.add_argument("--disable-accelerated-2d-canvas"),
    # chrome_options.add_argument("--proxy-server='direct://"),
    # chrome_options.add_argument("--proxy-bypass-list=*"),
    chrome_options.add_argument("--allow-running-insecure-content"),
    chrome_options.add_argument("--disable-web-security"),
    chrome_options.add_argument("--disable-client-side-phishing-detection"),
    chrome_options.add_argument("--disable-notifications"),
    chrome_options.add_argument("--mute-audio"),
    chrome_options.add_argument("--ignore-certificate-errors"),

    # Disable downloads
    chrome_options.add_experimental_option(
        'prefs', {
            'safebrowsing.enabled': 'false',
            'download.prompt_for_download': False,
            'download.default_directory': '/dev/null',
            'download_restrictions': 3,
            'profile.default_content_setting_values.notifications': 2,
        }
    )

    return chrome_options


def get_driver_proxy_capabilities(proxy: str):
    """
    Use a single proxy directly from the browser
    :param proxy:
    :return:
    """

    proxy = Proxy()
    proxy.proxy_type = ProxyType.MANUAL
    proxy.http_proxy = proxy
    proxy.ssl_proxy = proxy
    proxy.ftp_proxy = proxy
    proxy.auto_detect = False
    capabilities = webdriver.DesiredCapabilities.CHROME.copy()
    proxy.add_to_capabilities(capabilities)
    return capabilities


def build_driver(executable_path: str = None, options: Options = None, headless=True, timeout=20) -> webdriver:
    """
    Build Chrome driver instance
    :param executable_path: str
    :param options: Options
    :param headless: bool
    :param timeout: int
    :return: webdriver
    """

    kwargs = {}

    if executable_path is not None:
        kwargs['executable_path'] = executable_path

    kwargs['options'] = options if options is not None else get_default_driver_options(headless=headless)
    # kwargs['desired_capabilities'] = get_driver_proxy_capabilities('http://localhost:8888')

    driver = webdriver.Chrome(**kwargs)
    driver.set_page_load_timeout(timeout)

    return driver


def get_debugger_url(driver: webdriver) -> str:
    """
    Get Chrome debugger url
    :param driver: webdriver
    :return: str
    """

    chrome_debugger_url = f"http://{driver.capabilities['goog:chromeOptions']['debuggerAddress']}"
    debug('Chrome Debugger Url', chrome_debugger_url)
    return chrome_debugger_url


def get_websocket_debugger_url(driver: webdriver) -> str:
    """
    Get Chrome websocket debugger url
    :param driver: webdriver
    :return: str
    """

    chrome_debugger_url = get_debugger_url(driver)
    http = urllib3.PoolManager()
    response = json.loads(http.request('GET', chrome_debugger_url + '/json').data.decode())
    return response[0]['webSocketDebuggerUrl']
