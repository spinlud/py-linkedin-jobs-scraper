"""One time interactive login into a Chrome profile the scraper reuses across runs.

    python -m linkedin_jobs_scraper.login --user-data-dir ~/.linkedin-jobs-scraper

Opens a visible browser on the sign in page and waits for the session to appear. The
password is typed by the person running the command, into the browser: nothing here reads,
stores or transmits it.

Ticking "Keep me logged in" is what makes the profile durable. It leaves LinkedIn's remember
me cookie in the profile, which outlives the session cookie by a long way and lets the
scraper sign back in on its own once the session cookie is retired. It is unavailable on
accounts with two factor authentication enabled.
"""
import argparse
from pathlib import Path
from time import sleep

from .strategies.authenticated_strategy import Selectors
from .utils.chrome_driver import build_driver
from .utils.constants import HOME_URL
from .utils.logger import info
from .utils.session import (BROWSER_ID_COOKIE_NAME, REMEMBER_COOKIE_NAME, SIGN_IN_PATHS, get_cookie,
                            get_session_cookie)

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


def sign_in(user_data_dir: str, executable_path: str = None, binary_location: str = None) -> dict | None:
    """
    Open a visible browser and wait for a human to sign in

    Chrome locks a profile directory, so nothing else may have this one open while this runs.

    :param user_data_dir: str
    :param executable_path: str
    :param binary_location: str
    :return: dict the credentials the profile ends up holding, or None on timeout
    """

    driver = build_driver(
        executable_path=executable_path,
        binary_location=binary_location,
        headless=False,
        user_data_dir=user_data_dir,
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


def has_credentials(user_data_dir: str, executable_path: str = None, binary_location: str = None) -> bool:
    """
    Return True if the profile can authenticate without a human

    Either it holds a session, or it holds the remember me cookie LinkedIn issues a new
    session for. Costs one short lived headless browser, which is a better price than
    opening a window somebody then has to close.

    :param user_data_dir: str
    :param executable_path: str
    :param binary_location: str
    :return: bool
    """

    driver = build_driver(
        executable_path=executable_path,
        binary_location=binary_location,
        headless=True,
        user_data_dir=user_data_dir,
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


def ensure_session(user_data_dir: str, executable_path: str = None, binary_location: str = None) -> bool:
    """
    Sign in interactively, unless the profile can already authenticate on its own

    :param user_data_dir: str
    :param executable_path: str
    :param binary_location: str
    :return: bool
    """

    if has_credentials(user_data_dir, executable_path, binary_location):
        info('The browser profile already carries a session')
        return True

    info(f'No session in {user_data_dir}: opening a browser to sign in. '
         f'Tick "Keep me logged in" so the profile stays usable.')

    if not sign_in(user_data_dir, executable_path, binary_location):
        return False

    info('Signed in, the profile now carries a session')
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        prog='python -m linkedin_jobs_scraper.login',
        description='Sign in to LinkedIn once, into a Chrome profile the scraper reuses.')
    parser.add_argument('--user-data-dir', required=True,
                        help='Chrome profile directory to create or reuse')
    parser.add_argument('--chrome-executable-path', default=None, help='Path to chromedriver')
    parser.add_argument('--chrome-binary-location', default=None, help='Path to the Chrome binary')
    args = parser.parse_args()

    user_data_dir = Path(args.user_data_dir).expanduser()

    print(f'Chrome profile: {user_data_dir}')
    print('A browser window will open. Sign in there, ticking "Keep me logged in".')
    print(f'Waiting up to {LOGIN_TIMEOUT}s for the session to be established...')

    credentials = sign_in(str(user_data_dir), args.chrome_executable_path, args.chrome_binary_location)

    if credentials is None:
        print('Timed out: no session was established. The profile is unchanged.')
        return 1

    print('\nSigned in. The profile now carries the session.')
    print(f'Run the scraper with user_data_dir={user_data_dir} and it will reuse it.')
    print(f"\nli_at={credentials['li_at']}")

    if credentials['li_rm'] and credentials['bcookie']:
        # These two are what a host with no display needs: LinkedIn issues a session for the
        # pair, so a remote run never has to be handed a session cookie that will be retired.
        # Quoted so the lines can be pasted into a shell as they are: bcookie's value carries
        # double quotes and an ampersand, which the shell would otherwise read as syntax.
        print('\nTo run on a machine where no browser can be opened, export these instead:')
        print(f"\nLI_RM_COOKIE='{credentials['li_rm']}'")
        print(f"LI_BCOOKIE='{credentials['bcookie']}'")
    else:
        print('\nNo remember me cookie was issued, so this session cannot renew itself: sign in '
              'again with "Keep me logged in" ticked.')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
