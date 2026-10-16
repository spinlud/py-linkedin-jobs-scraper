"""One time interactive login into a Chrome profile the scraper reuses across runs.

    lijs login                                 # the default profile, ~/.lijs/chrome-profile
    lijs login --chrome-profile ~/my-profile   # any other profile

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
from pathlib import Path
from time import sleep
from typing import TYPE_CHECKING

from .strategies.authenticated_strategy import Selectors
from .utils.chrome_driver import build_driver
from .utils.constants import HOME_URL
from .utils.logger import info
from .utils.session import (BROWSER_ID_COOKIE_NAME, REMEMBER_COOKIE_NAME, SIGN_IN_PATHS, get_cookie,
                            get_session_cookie)
from .utils.session_source import (create_profile_dir, default_chrome_profile, remove_created_profile_dirs,
                                   resolve_login_profile)

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
    :return: str the session cookie, or None on timeout or once the browser is closed
    """

    elapsed = 0

    while elapsed < timeout:
        if not _is_browser_open(driver):
            return None

        li_at = get_session_cookie(driver)

        if li_at and not _is_sign_in_page(driver):
            return li_at

        sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    return None


def _is_browser_open(driver) -> bool:
    """
    Return False once the person has closed the browser window, or the browser has exited
    :param driver: webdriver
    :return: bool
    """

    try:
        return bool(driver.window_handles)
    except Exception:
        return False


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


def sign_in(chrome_user_data_dir: str | Path | None = None,
            executable_path: str = None,
            binary_location: str = None) -> dict | None:
    """
    Open a visible browser and wait for a human to sign in

    Chrome locks a profile directory, so nothing else may have this one open while this runs.
    A missing profile directory is created, owner only, before the browser opens. When the
    call ends without a session - a timeout, a closed browser, an exception or an interrupt -
    the directories it created are removed again, so a failed sign in leaves no empty profile
    behind. A directory that existed before the call is never removed.

    :param chrome_user_data_dir: str | Path | None the profile, the default one when None
    :param executable_path: str
    :param binary_location: str
    :return: dict the credentials the profile ends up holding, or None on timeout or a closed
        browser
    """

    profile = resolve_login_profile(chrome_user_data_dir)
    created_dirs = create_profile_dir(profile)
    driver = None
    credentials: dict | None = None

    try:
        driver = build_driver(
            executable_path=executable_path,
            binary_location=binary_location,
            headless=False,
            chrome_user_data_dir=str(profile),
            timeout=60)

        # An existing profile may still be signed in, in which case the home page is
        # enough and the sign in page would only redirect back to it
        driver.get(HOME_URL)
        sleep(3)

        if not get_session_cookie(driver):
            driver.get(LOGIN_URL)

        li_at = wait_for_session(driver)

        if li_at:
            credentials = {
                'li_at': li_at,
                'li_rm': get_cookie(driver, REMEMBER_COOKIE_NAME),
                'bcookie': get_cookie(driver, BROWSER_ID_COOKIE_NAME),
            }

        return credentials
    finally:
        # Chrome writes into the profile until it exits, so it is quit before any removal
        if driver is not None:
            try:
                driver.quit()
            except BaseException:
                pass

        if credentials is None:
            remove_created_profile_dirs(created_dirs)


def has_credentials(chrome_user_data_dir: str | Path | None = None,
                    executable_path: str = None,
                    binary_location: str = None) -> bool:
    """
    Return True if the profile can authenticate without a human

    Either it holds a session, or it holds the remember me cookie LinkedIn issues a new
    session for. Costs one short lived headless browser, which is a better price than
    opening a window somebody then has to close. A profile directory that does not exist
    holds nothing, and is answered without a browser, which would create it.

    :param chrome_user_data_dir: str | Path | None the profile, the default one when None
    :param executable_path: str
    :param binary_location: str
    :return: bool
    """

    profile = resolve_login_profile(chrome_user_data_dir)

    if not profile.is_dir():
        return False

    driver = build_driver(
        executable_path=executable_path,
        binary_location=binary_location,
        headless=True,
        chrome_user_data_dir=str(profile),
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


def ensure_session(chrome_user_data_dir: str | Path | None = None,
                   executable_path: str = None,
                   binary_location: str = None) -> bool:
    """
    Sign in interactively, unless the profile can already authenticate on its own

    :param chrome_user_data_dir: str | Path | None the profile, the default one when None
    :param executable_path: str
    :param binary_location: str
    :return: bool
    """

    profile = resolve_login_profile(chrome_user_data_dir)

    if has_credentials(profile, executable_path, binary_location):
        info('The browser profile already carries a session')
        return True

    info(f'No session in {profile}: opening a browser to sign in. '
         f'Tick "Keep me logged in" so the profile stays usable.')

    if not sign_in(profile, executable_path, binary_location):
        return False

    info('Signed in, the profile now carries a session')
    return True


def print_credentials(chrome_user_data_dir: str | Path,
                      credentials: dict,
                      colorizer: Colorizer | None = None) -> None:
    """
    Print copy-paste ready commands for reusing the session a fresh sign in produced

    The commands name the profile with --chrome-profile, except for the default profile,
    which the scraper falls back on by itself when no cookie is in the environment.

    :param chrome_user_data_dir: str | Path the profile that now carries the session
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

    is_default_profile = Path(chrome_user_data_dir).expanduser() == default_chrome_profile()
    profile_flag = '' if is_default_profile else f' --chrome-profile {shlex.quote(str(chrome_user_data_dir))}'

    print()
    print(green('✅ Signed in. The profile now carries the session.'))

    print()
    print(dim('# Search jobs'))
    print(f'{cyan("lijs")} {orange("jobs")} "Software Engineer" --location "Worldwide" --limit 5'
          f'{profile_flag}')

    print()
    print(dim('# Look up a single job'))
    print(f'{cyan("lijs")} {orange("job")} 123456789{profile_flag}')

    if credentials['li_rm'] and credentials['bcookie']:
        # The remember me pair is the remote-friendly path: LinkedIn issues a fresh session for
        # it, so a host with no display never has to be handed a session cookie that will be
        # retired. The values are single-quoted because bcookie carries double quotes and an
        # ampersand, which an unquoted shell would read as syntax; the exports stay uncoloured
        # so they copy cleanly.
        print()
        print(dim('# Instead of the profile, you can export these environment variables:'))
        print(f"{cyan('LI_RM_COOKIE')}{orange('=')}'{credentials['li_rm']}'")
        print(f"{cyan('LI_BCOOKIE')}{orange('=')}'{credentials['bcookie']}'")
    else:
        print()
        print(yellow('No remember me cookie was issued, so this session cannot renew itself: '
                     'sign in again with "Keep me logged in" ticked.'))
