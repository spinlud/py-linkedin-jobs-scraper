"""Ask LinkedIn for a session from the remember me pair, using nothing but selenium.

Standalone on purpose: this is meant to run on a host that has no copy of the repository -
a VM, a container, anything reachable by scp - so it imports nothing from
linkedin_jobs_scraper and duplicates the few things that matter. Copy this one file across
and run it. It answers whether a pair issued on one machine can be redeemed from another,
with a different IP, operating system and Sec-CH-UA-Platform, which is the experiment
recorded in docs/remember-me-portability.md. Nothing is scraped: one browser, one
authenticated request, then the cookie jar is polled for a session.

    LI_RM_COOKIE='...' LI_BCOOKIE='"v=2&..."' python remote_probe.py

Getting the two values across a shell without mangling the quotes in bcookie is easier with
a file, which docker also takes directly:

    docker run --rm --security-opt seccomp=unconfined --env-file cookies.env \
        -v "$PWD:/app" -w /app <image> python -u remote_probe.py

Exit code 0 means LinkedIn issued a session, which is the only strong result here: a refusal
can equally be bot management, throttling or an interstitial, so redeem the same pair from
the machine that issued it as a control.

The browser fingerprint has to match what the scraper presents, or a refusal says nothing
about the credential. Two signals get a session ended on sight: the HeadlessChrome token in
the User-Agent, and navigator.webdriver via the enable-automation switch.

Environment:
    LI_RM_COOKIE    required, the remember me credential
    LI_BCOOKIE      required, the browser id it was issued to
    HEADLESS        'false' to watch it work in a visible browser, default 'true'
"""
import os
import sys
from time import sleep, time
from urllib.parse import urlsplit

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions

HOME_URL = 'https://www.linkedin.com'
FEED_URL = 'https://www.linkedin.com/feed/'

SESSION_COOKIE_NAME = 'li_at'
REMEMBER_COOKIE_NAME = 'li_rm'
BROWSER_ID_COOKIE_NAME = 'bcookie'

# bcookie sits on a different domain from the other two, odd as the leading dot on a host
# name looks. Injecting either on the wrong one leaves the browser unauthenticated.
REMEMBER_COOKIE_DOMAIN = '.www.linkedin.com'
BROWSER_ID_COOKIE_DOMAIN = '.linkedin.com'

# Chrome discards a cookie carrying no expiry as soon as the browser closes
REMEMBER_COOKIE_MAX_AGE = 365 * 24 * 60 * 60

HEADLESS_USER_AGENT_TOKEN = 'HeadlessChrome/'
BROWSER_USER_AGENT_TOKEN = 'Chrome/'
USER_AGENT_HINTS = ['architecture', 'bitness', 'model', 'platformVersion', 'fullVersionList']

# The paths LinkedIn redirects to when it refuses a credential
SIGN_IN_PATHS = ('/uas/login', '/login', '/checkpoint/lg/login', '/authwall')

# A navigation returns before the response carrying the session cookie is processed, since
# the page load strategy is 'none'
SESSION_WAIT_TIMEOUT = 15

HEADLESS = os.environ.get('HEADLESS', 'true').lower() != 'false'


def build_driver() -> webdriver.Chrome:
    """
    Launch Chrome presenting what the scraper presents
    """

    options = ChromeOptions()
    options.page_load_strategy = 'none'

    if HEADLESS:
        options.add_argument('--headless=new')

    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument('--window-size=1472,828')
    options.add_argument('--lang=en-GB')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-setuid-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-notifications')
    options.add_argument('--mute-audio')

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(45)
    return driver


def mask_headless_user_agent(driver: webdriver.Chrome) -> str | None:
    """
    Replace the headless token in the User-Agent, keeping the client hints coherent

    Must be called on a secure context: navigator.userAgentData, which carries the values
    the override has to preserve, is not exposed on the blank page a driver starts on.
    acceptLanguage is deliberately not passed - Chrome appends a second quality value to
    every entry, and --lang already yields a correct Accept-Language.

    :param driver: webdriver
    :return: str the masked User-Agent, or None if there was nothing to mask
    """

    user_agent = driver.execute_script('return navigator.userAgent')

    if not user_agent or HEADLESS_USER_AGENT_TOKEN not in user_agent:
        return None

    masked = user_agent.replace(HEADLESS_USER_AGENT_TOKEN, BROWSER_USER_AGENT_TOKEN)

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

    override = {'userAgent': masked}

    if brands and hints:
        override['userAgentMetadata'] = {
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
    else:
        print('  client hints unavailable, the Sec-CH-UA headers will not match the User-Agent')

    driver.execute_cdp_cmd('Network.setUserAgentOverride', override)
    return masked


def set_cookie(driver: webdriver.Chrome, name: str, value: str, domain: str) -> None:
    driver.add_cookie({
        'name': name,
        'value': value,
        'domain': domain,
        'expiry': int(time() + REMEMBER_COOKIE_MAX_AGE),
    })


def get_cookie(driver: webdriver.Chrome, name: str) -> str | None:
    try:
        cookie = driver.get_cookie(name)
    except BaseException:
        return None

    return cookie['value'] if cookie and 'value' in cookie else None


def wait_for_session(driver: webdriver.Chrome) -> str | None:
    """
    Poll until the browser holds a session cookie
    """

    elapsed = 0
    sleep_time = 0.2

    while elapsed < SESSION_WAIT_TIMEOUT:
        li_at = get_cookie(driver, SESSION_COOKIE_NAME)

        if li_at:
            return li_at

        sleep(sleep_time)
        elapsed += sleep_time

    return None


def describe_client(driver: webdriver.Chrome) -> None:
    """
    Report the signals LinkedIn sees, which are what changes when the pair moves machine
    """

    client = driver.execute_script(
        '''
            return {
                userAgent: navigator.userAgent,
                webdriver: navigator.webdriver,
                platform: navigator.userAgentData && navigator.userAgentData.platform,
                languages: (navigator.languages || []).join(','),
            };
        ''')

    print(f'  user agent : {client.get("userAgent")}')
    print(f'  platform   : {client.get("platform")}')
    print(f'  webdriver  : {client.get("webdriver")}')
    print(f'  languages  : {client.get("languages")}')


def main() -> int:
    li_rm = os.environ.get('LI_RM_COOKIE')
    bcookie = os.environ.get('LI_BCOOKIE')

    if not li_rm or not bcookie:
        print('LI_RM_COOKIE and LI_BCOOKIE are both required. Get them from a machine with a '
              'display:\n  python -m linkedin_jobs_scraper.login --user-data-dir <path>')
        return 2

    if os.environ.get('LI_AT_COOKIE'):
        print('LI_AT_COOKIE is also set, and a session handed over would mask a refusal of the '
              'pair. Unset it.')
        return 2

    print(f'li_rm   : {len(li_rm)} chars, starts {li_rm[:3]!r}')
    print(f'bcookie : {len(bcookie)} chars, starts {bcookie[:5]!r}')
    print(f'headless: {HEADLESS}\n')

    driver = build_driver()

    try:
        # A cookie can only be set for the domain the browser is on, and the client hints the
        # masking reads are unavailable on the blank page a driver starts on. This request is
        # unauthenticated, so it can afford to carry the headless token.
        print(f'--- opening {HOME_URL}')
        driver.get(HOME_URL)
        sleep(2)
        mask_headless_user_agent(driver)
        describe_client(driver)

        set_cookie(driver, REMEMBER_COOKIE_NAME, li_rm, REMEMBER_COOKIE_DOMAIN)
        set_cookie(driver, BROWSER_ID_COOKIE_NAME, bcookie, BROWSER_ID_COOKIE_DOMAIN)

        print(f'\n--- injected {REMEMBER_COOKIE_NAME} and {BROWSER_ID_COOKIE_NAME}, '
              f'requesting {FEED_URL}')
        driver.get(FEED_URL)
        li_at = wait_for_session(driver)

        landed = driver.current_url
        print(f'  landed on  : {landed}')
        print(f'  {REMEMBER_COOKIE_NAME} still held: '
              f'{bool(get_cookie(driver, REMEMBER_COOKIE_NAME))}')

        print('\n================ RESULT ================')

        if li_at:
            print(f'SESSION ISSUED: li_at, {len(li_at)} chars')
            print('The pair is redeemable from this machine.')
            print(f'\n{li_at}')
            return 0

        if any(urlsplit(landed).path.startswith(path) for path in SIGN_IN_PATHS):
            print('REFUSED: LinkedIn redirected to a sign in page and issued no session.')
        else:
            print('NO SESSION: no li_at appeared, and the page is not a sign in page either.')

        print('A refusal is weak evidence on its own - it can be the credential, bot '
              'management, throttling or an interstitial. Redeem the same pair from the '
              'machine that issued it, minutes apart, as a control.')
        return 1
    finally:
        try:
            driver.quit()
        except BaseException:
            pass


if __name__ == '__main__':
    raise SystemExit(main())
