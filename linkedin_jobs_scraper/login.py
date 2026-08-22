"""One time interactive login into a Chrome profile the scraper reuses across runs.

    linkedin-jobs-scraper login --chrome-user-data-dir ~/.linkedin-jobs-scraper

Opens a visible browser on the sign in page and waits for the session to appear. The
password is typed by the person running the command, into the browser: nothing here reads,
stores or transmits it.

Ticking "Keep me logged in" is what makes the profile durable. It leaves LinkedIn's remember
me cookie in the profile, which outlives the session cookie by a long way and lets the
scraper sign back in on its own once the session cookie is retired. It is unavailable on
accounts with two factor authentication enabled.
"""
from __future__ import annotations

import shlex
from time import sleep
from typing import TYPE_CHECKING

from .strategies.authenticated_strategy import Selectors
from .utils.chrome_driver import build_driver
from .utils.constants import HOME_URL
from .utils.logger import info
from .utils.session import (BROWSER_ID_COOKIE_NAME, REMEMBER_COOKIE_NAME, SIGN_IN_PATHS, get_cookie,
                            get_session_cookie)

if TYPE_CHECKING:
    from .cli.color import Colorizer

LOGIN_URL = 'https://www.linkedin.com/login'

# Long enough for a password manager, a two factor prompt and the consent interstitials
# LinkedIn interposes after a fresh sign in.
LOGIN_TIMEOUT = 600

POLL_INTERVAL = 1


def wait_for_session(driver, timeout: int = LOGIN_TIMEOUT) -> str | None:
    """
    Poll until the browser holds a session past the sign in pages

    The application shell is not a usable signal on its own: LinkedIn interposes consent
    interstitials after a fresh sign in, and those pages carry an established session while
    rendering none of the shell. Leaving the sign in flow behind is what marks success.

    :param driver: webdriver
    :param timeout: int
    :return: str the session cookie, or None on timeout
    """

    elapsed = 0

    while elapsed < timeout:
        li_at = get_session_cookie(driver)

        if li_at and not _is_sign_in_page(driver):
            return li_at

        sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    return None


def _is_sign_in_page(driver) -> bool:
    """
    Return True while the browser is still on a page that asks who you are
    :param driver: webdriver
    :return: bool
    """

    try:
        url = driver.current_url or ''
    except BaseException:
        return True

    if any(path in url for path in SIGN_IN_PATHS):
        return True

    try:
        return bool(driver.execute_script(
            'return !!document.querySelector(arguments[0]);', Selectors.signInForm))
    except BaseException:
        return True


def sign_in(chrome_user_data_dir: str, executable_path: str = None, binary_location: str = None) -> dict | None:
    """
    Open a visible browser and wait for a human to sign in

    Chrome locks a profile directory, so nothing else may have this one open while this runs.

    :param chrome_user_data_dir: str
    :param executable_path: str
    :param binary_location: str
    :return: dict the credentials the profile ends up holding, or None on timeout
    """

    driver = build_driver(
        executable_path=executable_path,
        binary_location=binary_location,
        headless=False,
        chrome_user_data_dir=chrome_user_data_dir,
        timeout=60)

    try:
        # An existing profile may still be signed in, in which case the home page is
        # enough and the sign in page would only redirect back to it
        driver.get(HOME_URL)
        sleep(3)

        if not get_session_cookie(driver):
            driver.get(LOGIN_URL)

        li_at = wait_for_session(driver)

        if not li_at:
            return None

        return {
            'li_at': li_at,
            'li_rm': get_cookie(driver, REMEMBER_COOKIE_NAME),
            'bcookie': get_cookie(driver, BROWSER_ID_COOKIE_NAME),
        }
    finally:
        try:
            driver.quit()
        except BaseException:
            pass


def has_credentials(chrome_user_data_dir: str, executable_path: str = None, binary_location: str = None) -> bool:
    """
    Return True if the profile can authenticate without a human

    Either it holds a session, or it holds the remember me cookie LinkedIn issues a new
    session for. Costs one short lived headless browser, which is a better price than
    opening a window somebody then has to close.

    :param chrome_user_data_dir: str
    :param executable_path: str
    :param binary_location: str
    :return: bool
    """

    driver = build_driver(
        executable_path=executable_path,
        binary_location=binary_location,
        headless=True,
        chrome_user_data_dir=chrome_user_data_dir,
        timeout=60)

    try:
        driver.get(HOME_URL)
        sleep(3)
        return bool(get_session_cookie(driver) or get_cookie(driver, REMEMBER_COOKIE_NAME))
    except BaseException:
        return False
    finally:
        try:
            driver.quit()
        except BaseException:
            pass


def ensure_session(chrome_user_data_dir: str, executable_path: str = None, binary_location: str = None) -> bool:
    """
    Sign in interactively, unless the profile can already authenticate on its own

    :param chrome_user_data_dir: str
    :param executable_path: str
    :param binary_location: str
    :return: bool
    """

    if has_credentials(chrome_user_data_dir, executable_path, binary_location):
        info('The browser profile already carries a session')
        return True

    info(f'No session in {chrome_user_data_dir}: opening a browser to sign in. '
         f'Tick "Keep me logged in" so the profile stays usable.')

    if not sign_in(chrome_user_data_dir, executable_path, binary_location):
        return False

    info('Signed in, the profile now carries a session')
    return True


def print_credentials(chrome_user_data_dir: str,
                      credentials: dict,
                      colorizer: Colorizer | None = None) -> None:
    """
    Print copy-paste ready commands for reusing the session a fresh sign in produced

    :param chrome_user_data_dir: str the profile that now carries the session
    :param credentials: dict the mapping sign_in returns
    :param colorizer: Colorizer | None applies ANSI styling when present, plain text otherwise
    :return: None
    """

    def plain(text: str) -> str:
        return text

    green = colorizer.green if colorizer is not None else plain
    yellow = colorizer.yellow if colorizer is not None else plain
    dim = colorizer.dim if colorizer is not None else plain
    cyan = colorizer.cyan if colorizer is not None else plain
    orange = colorizer.orange if colorizer is not None else plain

    profile = shlex.quote(chrome_user_data_dir)

    print()
    print(green('✅ Signed in. The profile now carries the session.'))

    print()
    print(dim('# Search jobs'))
    print(f'{cyan("lijs")} {orange("jobs")} "Software Engineer" --location "Worldwide" --limit 5 \\')
    print(f'  --chrome-user-data-dir {profile}')

    print()
    print(dim('# Look up a single job'))
    print(f'{cyan("lijs")} {orange("job")} 123456789 --chrome-user-data-dir {profile}')

    if credentials['li_rm'] and credentials['bcookie']:
        # The remember me pair is the remote-friendly path: LinkedIn issues a fresh session for
        # it, so a host with no display never has to be handed a session cookie that will be
        # retired. The values are single-quoted because bcookie carries double quotes and an
        # ampersand, which an unquoted shell would read as syntax; the exports stay uncoloured
        # so they copy cleanly.
        print()
        print(dim('# Instead of --chrome-user-data-dir, you can export these environment variables:'))
        print(f"{cyan('LI_RM_COOKIE')}{orange('=')}'{credentials['li_rm']}'")
        print(f"{cyan('LI_BCOOKIE')}{orange('=')}'{credentials['bcookie']}'")
    else:
        print()
        print(yellow('No remember me cookie was issued, so this session cannot renew itself: '
                     'sign in again with "Keep me logged in" ticked.'))
