"""The cookies a LinkedIn session is made of: reading them, and injecting them."""
from time import sleep, time
from selenium import webdriver
from .logger import warn

SESSION_COOKIE_NAME = 'li_at'

# LinkedIn sets the cookie on this domain itself, odd as the leading dot on a host name
# looks. Injecting it anywhere else leaves the session unauthenticated.
SESSION_COOKIE_DOMAIN = '.www.linkedin.com'

# The remember me cookie, issued only to a sign in that ticked "Keep me logged in". It
# lasts a year, outliving the session cookie by a long way, and LinkedIn accepts it in
# place of a password when minting a new session.
REMEMBER_COOKIE_NAME = 'li_rm'
REMEMBER_COOKIE_DOMAIN = SESSION_COOKIE_DOMAIN

# The browser id the remember me cookie was issued to. LinkedIn reissues a session for the
# pair and for nothing less: measured on a pristine profile, li_rm on its own is turned
# away at the sign in page, and so is li_rm next to a different browser's id.
BROWSER_ID_COOKIE_NAME = 'bcookie'
BROWSER_ID_COOKIE_DOMAIN = '.linkedin.com'

# Chrome discards a cookie carrying no expiry as soon as the browser closes, which would
# leave a persistent profile holding a session and nothing able to renew it. LinkedIn issues
# the pair with exactly this lifetime, so an injected one is given the same; guessing long is
# harmless either way, since a pair LinkedIn no longer honours is refused and falls back.
REMEMBER_COOKIE_MAX_AGE = 365 * 24 * 60 * 60

# LinkedIn refuses a session in two ways, and only one of them clears the cookie: it either
# sends li_at back with an expiry in the past, or redirects to one of these paths while
# leaving the cookie in the jar. Both have been observed on the same cookie.
SIGN_IN_PATHS = ('/uas/login', '/login', '/checkpoint/lg/login', '/authwall')

# How long to wait for a navigation to put the browser back on LinkedIn. The driver uses a
# 'none' page load strategy, so a navigation returns long before its page is on screen.
DOMAIN_WAIT_TIMEOUT = 10


def is_on_linkedin(driver: webdriver) -> bool:
    """
    Return True if the browser is showing a document served by LinkedIn

    Everything below reads or writes the cookie jar, and the jar the driver exposes is the
    one belonging to the page the browser is on. On an error page - a network failure, or the
    HTTP 429 LinkedIn answers a fast run with - it reads empty whatever the browser holds,
    and injecting a cookie there raises. So no conclusion about a session may be drawn
    without asking this first.

    :param driver: webdriver
    :return: bool
    """

    try:
        hostname = driver.execute_script('return document.location.hostname')
    except BaseException:
        return False

    return bool(hostname) and hostname.endswith('linkedin.com')


def wait_for_linkedin(driver: webdriver, timeout: int = DOMAIN_WAIT_TIMEOUT) -> bool:
    """
    Poll until the browser is on a LinkedIn document
    :param driver: webdriver
    :param timeout: int
    :return: bool
    """

    elapsed = 0
    sleep_time = 0.1

    while elapsed < timeout:
        if is_on_linkedin(driver):
            return True

        sleep(sleep_time)
        elapsed += sleep_time

    return False


def get_cookie(driver: webdriver, name: str) -> str | None:
    """
    Read a cookie held by the browser for the page it is on
    :param driver: webdriver
    :param name: str
    :return: str
    """

    try:
        cookie = driver.get_cookie(name)
    except BaseException:
        return None

    return cookie['value'] if cookie and 'value' in cookie else None


def set_cookie(driver: webdriver, name: str, value: str, domain: str, max_age: int = None) -> bool:
    """
    Inject a cookie into the browser
    :param driver: webdriver
    :param name: str
    :param value: str
    :param domain: str
    :param max_age: int seconds to keep it for, or None to drop it when the browser closes
    :return: bool
    """

    cookie = {'name': name, 'value': value, 'domain': domain}

    if max_age is not None:
        cookie['expiry'] = int(time() + max_age)

    try:
        driver.add_cookie(cookie)
        return True
    except BaseException as e:
        warn(f'Failed to set the {name} cookie', e)
        return False


def get_session_cookie(driver: webdriver) -> str | None:
    """
    Read the session cookie currently held by the browser
    :param driver: webdriver
    :return: str
    """

    return get_cookie(driver, SESSION_COOKIE_NAME)


def set_session_cookie(driver: webdriver, li_at: str) -> bool:
    """
    Inject a session cookie into the browser
    :param driver: webdriver
    :param li_at: str
    :return: bool
    """

    return set_cookie(driver, SESSION_COOKIE_NAME, li_at, SESSION_COOKIE_DOMAIN)


def set_remember_me_cookies(driver: webdriver, li_rm: str, bcookie: str) -> bool:
    """
    Inject the credential LinkedIn accepts in place of a password

    Both halves are required, and the browser id replaces the one the browser generated
    for itself: the pair only works together. They are injected to last, so that a
    persistent profile keeps them and can renew its own session once the environment that
    supplied them is gone.

    :param driver: webdriver
    :param li_rm: str
    :param bcookie: str
    :return: bool
    """

    return (set_cookie(driver, REMEMBER_COOKIE_NAME, li_rm, REMEMBER_COOKIE_DOMAIN,
                       REMEMBER_COOKIE_MAX_AGE)
            and set_cookie(driver, BROWSER_ID_COOKIE_NAME, bcookie, BROWSER_ID_COOKIE_DOMAIN,
                           REMEMBER_COOKIE_MAX_AGE))
