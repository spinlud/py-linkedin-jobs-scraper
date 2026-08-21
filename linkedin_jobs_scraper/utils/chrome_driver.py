from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from linkedin_jobs_scraper.utils.logger import debug, warn

# Chrome advertises its headless mode in the User-Agent, both in the HTTP header and in
# navigator.userAgent. LinkedIn sees that token on every request carrying the session
# cookie, so it is replaced with the regular browser one.
HEADLESS_USER_AGENT_TOKEN = 'HeadlessChrome/'
BROWSER_USER_AGENT_TOKEN = 'Chrome/'

# High entropy client hint values, read from the browser itself so that the overridden
# User-Agent and the Sec-CH-UA headers keep telling the same story.
USER_AGENT_HINTS = ['architecture', 'bitness', 'model', 'platformVersion', 'fullVersionList']

# Resolving the User-Agent costs a browser start, so it is done once per process
_masked_user_agent: str | None = None
_is_user_agent_resolved = False


def get_default_driver_options(
        width: int = 1472,
        height: int = 828,
        headless: bool = True,
        chrome_user_data_dir: str | None = None,
        user_agent: str | None = None) -> ChromeOptions:
    """
    Generate default Chrome driver options
    :param width: int
    :param height: int
    :param headless: bool
    :param chrome_user_data_dir: str
    :param user_agent: str
    :return: Options
    """

    chrome_options = ChromeOptions()
    chrome_options.page_load_strategy = 'none'

    if headless:
        chrome_options.add_argument("--headless=new")

    if user_agent:
        # Set at launch rather than over CDP so that every target inherits it. Tabs the
        # page opens - the apply link opens one, and it lands on LinkedIn before being
        # redirected off site - are separate targets and would otherwise still announce
        # themselves as headless while carrying the session cookie.
        chrome_options.add_argument(f"--user-agent={user_agent}")

    if chrome_user_data_dir:
        # Chrome locks the directory, so a profile cannot be shared by two live browsers
        chrome_options.add_argument(f"--user-data-dir={Path(chrome_user_data_dir).expanduser().resolve()}")

    # navigator.webdriver is the most checked automation signal and is set by the
    # enable-automation switch, which Chromedriver passes on its own unless excluded
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument(f"--window-size={width},{height}")
    chrome_options.add_argument("--lang=en-GB")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-setuid-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-accelerated-2d-canvas")
    chrome_options.add_argument("--allow-running-insecure-content")
    chrome_options.add_argument("--disable-client-side-phishing-detection")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--mute-audio")
    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.add_argument("--remote-allow-origins=*")

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


def resolve_masked_user_agent(
        executable_path: str = None,
        binary_location: str = None) -> str | None:
    """
    Learn the browser's own User-Agent and return it without the headless token

    Costs one short lived browser, once per process, because the value is only knowable by
    asking the browser and it has to be known before the real one is launched. A resolved
    answer is cached, so the price is paid once; a failure is not, so it can be retried.

    :param executable_path: str
    :param binary_location: str
    :return: str the masked User-Agent, or None if there is nothing to mask
    """

    global _masked_user_agent, _is_user_agent_resolved

    if _is_user_agent_resolved:
        return _masked_user_agent

    options = ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])

    if binary_location:
        options.binary_location = binary_location

    driver = None

    try:
        driver = webdriver.Chrome(
            options=options,
            service=ChromeService(executable_path) if executable_path else None)

        # navigator.userAgent, unlike navigator.userAgentData, is readable on the blank
        # page the driver starts on, so no navigation is needed
        user_agent = driver.execute_script('return navigator.userAgent')
    except BaseException as e:
        # Left unresolved on purpose, so a later driver tries again: a browser that cannot
        # start at all fails the run anyway, and caching one transient failure would drop
        # the masking for the whole process
        warn('Failed to resolve the browser User-Agent, headless runs will announce themselves', e)
        return None
    finally:
        if driver is not None:
            try:
                driver.quit()
            except BaseException:
                pass

    _is_user_agent_resolved = True

    if not user_agent or HEADLESS_USER_AGENT_TOKEN not in user_agent:
        return None

    _masked_user_agent = user_agent.replace(HEADLESS_USER_AGENT_TOKEN, BROWSER_USER_AGENT_TOKEN)
    debug('Resolved masked User-Agent', _masked_user_agent)
    return _masked_user_agent


def mask_headless_user_agent(driver: webdriver) -> str | None:
    """
    Replace the headless token in the User-Agent, keeping the client hints coherent

    Must be called on a secure context: navigator.userAgentData, which carries the client
    hint values the override has to preserve, is not exposed on the blank page a driver
    starts on. Overriding the User-Agent without those values would blank out the
    Sec-CH-UA headers, which is an anomaly of its own.

    :param driver: webdriver
    :return: str the masked User-Agent, or None if no masking was needed or possible
    """

    try:
        user_agent = driver.execute_script('return navigator.userAgent')
    except BaseException as e:
        warn('Failed to read the browser User-Agent', e)
        return None

    if not user_agent or HEADLESS_USER_AGENT_TOKEN not in user_agent:
        return None

    masked_user_agent = user_agent.replace(HEADLESS_USER_AGENT_TOKEN, BROWSER_USER_AGENT_TOKEN)

    # The command also accepts acceptLanguage, which is deliberately left out: Chrome
    # appends a second quality value to every entry, yielding a malformed
    # 'en-GB,en-US;q=0.9;q=0.9,...'. The lang argument already produces a correct one.
    params = {'userAgent': masked_user_agent}

    metadata = _get_user_agent_metadata(driver)

    if metadata is not None:
        params['userAgentMetadata'] = metadata
    else:
        warn('Client hint values are unavailable, the User-Agent override may drop the Sec-CH-UA headers')

    try:
        driver.execute_cdp_cmd('Network.setUserAgentOverride', params)
    except BaseException as e:
        warn('Failed to override the User-Agent', e)
        return None

    debug('Masked headless User-Agent', masked_user_agent)
    return masked_user_agent


def _get_user_agent_metadata(driver: webdriver) -> dict | None:
    """
    Read the client hint values the browser would send on its own
    :param driver: webdriver
    :return: dict
    """

    try:
        brands = driver.execute_script('return navigator.userAgentData && navigator.userAgentData.brands')
        hints = driver.execute_async_script(
            '''
                const callback = arguments[arguments.length - 1];

                if (!navigator.userAgentData) {
                    callback(null);
                    return;
                }

                navigator.userAgentData.getHighEntropyValues(arguments[0])
                    .then(values => callback(values))
                    .catch(() => callback(null));
            ''',
            USER_AGENT_HINTS)
    except BaseException:
        return None

    if not brands or not hints:
        return None

    return {
        'brands': brands,
        'fullVersionList': hints.get('fullVersionList', brands),
        'platform': hints.get('platform', ''),
        'platformVersion': hints.get('platformVersion', ''),
        'architecture': hints.get('architecture', ''),
        'model': hints.get('model', ''),
        'bitness': hints.get('bitness', ''),
        'mobile': bool(hints.get('mobile', False)),
        'wow64': bool(hints.get('wow64', False)),
    }


def build_driver(
        executable_path: str = None,    # chromedriver
        binary_location: str = None,    # Chrome or Chromium
        options: ChromeOptions = None,
        headless=True,
        chrome_user_data_dir: str | None = None,
        timeout=20) -> webdriver:
    """
    Build Chrome driver instance
    :param executable_path: str
    :param binary_location: str
    :param options: ChromeOptions
    :param headless: bool
    :param chrome_user_data_dir: str
    :param timeout: int
    :return: webdriver
    """

    chrome_service = ChromeService(executable_path) if executable_path else None

    if options is not None:
        # Caller supplied options are taken as given; mask_headless_user_agent still
        # covers the main target over CDP
        chrome_options = options
    else:
        chrome_options = get_default_driver_options(
            headless=headless,
            chrome_user_data_dir=chrome_user_data_dir,
            user_agent=resolve_masked_user_agent(executable_path, binary_location) if headless else None)

    if binary_location:
        chrome_options.binary_location = binary_location

    driver = webdriver.Chrome(options=chrome_options, service=chrome_service)
    driver.set_page_load_timeout(timeout)

    return driver
