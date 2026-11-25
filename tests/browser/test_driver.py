from __future__ import annotations

from pathlib import Path

import pytest

from linkedin_jobs_scraper import LinkedinScraper
from linkedin_jobs_scraper.utils.chrome_driver import build_driver, quit_driver
from linkedin_jobs_scraper.utils.constants import HOME_URL
from linkedin_jobs_scraper.utils.page_script import run_script
from linkedin_jobs_scraper.utils.session import wait_for_linkedin

from .conftest import Launch
from .fake_linkedin import FakeLinkedin


def test_the_scraper_drives_a_browser_started_with_the_package_options(
    linkedin: FakeLinkedin, launches: list[Launch]
) -> None:
    LinkedinScraper(slow_mo=0.2).scrape_job('1')

    _user_agent_reader, browser = launches
    assert browser.driver.capabilities['pageLoadStrategy'] == 'none'
    user_agents = {request.headers['User-Agent'] for request in linkedin.requests}
    assert len(user_agents) == 1
    user_agent = user_agents.pop()
    assert 'Headless' not in user_agent
    # Set at launch, not only on the page that is open
    assert f'--user-agent={user_agent}' in browser.requested_arguments


def test_a_page_sees_no_automation() -> None:
    driver = build_driver()
    try:
        driver.get(HOME_URL)
        assert wait_for_linkedin(driver)
        assert run_script(driver, 'return navigator.webdriver') is False
        assert 'Headless' not in str(run_script(driver, 'return navigator.userAgent'))
    finally:
        quit_driver(driver)


def test_a_chromedriver_on_path_is_not_picked_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = tmp_path / 'calls'
    calls.touch()
    chromedriver = tmp_path / 'chromedriver'
    chromedriver.write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\necho ChromeDriver 158.0.0.0\n')
    chromedriver.chmod(0o755)
    monkeypatch.setenv('PATH', str(tmp_path), prepend=':')

    quit_driver(build_driver())

    # Selenium Manager may ask it for its version, and then uses its own
    assert '--port' not in calls.read_text()
