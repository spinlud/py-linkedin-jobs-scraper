from __future__ import annotations

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.wait import WebDriverWait

from linkedin_jobs_scraper.utils.chrome_driver import build_driver, quit_driver
from linkedin_jobs_scraper.utils.constants import HOME_URL
from linkedin_jobs_scraper.utils.page_script import run_script

from .fake_linkedin import FakeLinkedin
from .pages import HOME_TEXT


def block_arguments(port: int) -> tuple[str, ...]:
    """LinkedIn is the local server on that port. Every other host is unknown, and no proxy is
    asked for it instead."""
    return (
        f'--host-resolver-rules=MAP www.linkedin.com:443 127.0.0.1:{port},MAP * ^NOTFOUND',
        '--no-proxy-server',
    )


def assert_blocked(fake: FakeLinkedin) -> None:
    """Open the server under names that reach it without the block, so that a block that does not
    hold lets nothing off this machine."""
    driver = build_driver()

    def shows(url: str, *texts: str) -> bool:
        def has_texts(d: WebDriver) -> bool:
            shown = str(run_script(d, 'return document.body && document.body.innerText'))
            return all(text in shown for text in texts)

        driver.get(url)
        try:
            return WebDriverWait(driver, 5, poll_frequency=0.05).until(has_texts)
        except TimeoutException:
            return False

    try:
        for host in ('127.0.0.1', 'localhost'):
            is_blocked = shows(f'https://{host}:{fake.port}/', host, 'ERR_NAME_NOT_RESOLVED')
            assert is_blocked, f'{host} is not blocked'
        assert fake.requests == [], 'a blocked host was asked for a page'
        assert shows(HOME_URL, HOME_TEXT), 'LinkedIn is not the local server'
    finally:
        quit_driver(driver)
