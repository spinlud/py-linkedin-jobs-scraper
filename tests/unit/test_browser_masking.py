"""The launch options and the CDP call that keep the browser from looking automated."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from selenium.webdriver.chrome.options import Options

from linkedin_jobs_scraper.utils import chrome_driver
from linkedin_jobs_scraper.utils.chrome_driver import (
    ChromedriverPaths,
    build_driver,
    mask_headless_user_agent,
)

HEADLESS_USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) '
    'HeadlessChrome/154.0.0.0 Safari/537.36'
)
MASKED_USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/154.0.0.0 Safari/537.36'
)


@pytest.fixture
def launches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[Options]:
    """The options of each browser launched. Each browser answers a headless User-Agent."""
    launched: list[Options] = []

    def launch(options: Options, service: object) -> MagicMock:
        launched.append(options)
        driver = MagicMock()
        driver.execute_script.return_value = HEADLESS_USER_AGENT
        return driver

    paths = ChromedriverPaths(str(tmp_path / 'chromedriver'), str(tmp_path / 'chrome'))
    monkeypatch.setattr(chrome_driver, 'resolve_chromedriver_paths', lambda _binary: paths)
    monkeypatch.setattr(chrome_driver, 'ChromeService', MagicMock())
    monkeypatch.setattr(chrome_driver.webdriver, 'Chrome', launch)
    monkeypatch.setattr(chrome_driver, '_masked_user_agent', None)
    monkeypatch.setattr(chrome_driver, '_is_user_agent_resolved', False)
    return launched


@pytest.mark.parametrize('headless', [True, False])
def test_the_browser_does_not_announce_automation(launches: list[Options], headless: bool) -> None:
    build_driver(headless=headless)
    options = launches[-1]

    assert '--disable-blink-features=AutomationControlled' in options.arguments
    assert options.experimental_options['excludeSwitches'] == ['enable-automation']
    assert options.experimental_options['useAutomationExtension'] is False
    assert '--enable-automation' not in options.arguments


def test_web_security_stays_on(launches: list[Options], tmp_path: Path) -> None:
    build_driver(chrome_user_data_dir=str(tmp_path))

    assert not any('disable-web-security' in argument for argument in launches[-1].arguments)


def test_pages_are_asked_for_in_english(launches: list[Options]) -> None:
    build_driver()

    assert '--lang=en-GB' in launches[-1].arguments


def test_a_navigation_is_not_waited_for(launches: list[Options]) -> None:
    build_driver()

    assert launches[-1].page_load_strategy == 'none'


def test_a_headless_browser_is_launched_with_its_own_user_agent_unmarked(
    launches: list[Options],
) -> None:
    build_driver(headless=True)
    probe, browser = launches

    assert '--headless=new' in browser.arguments
    assert f'--user-agent={MASKED_USER_AGENT}' in browser.arguments
    assert probe.experimental_options['excludeSwitches'] == ['enable-automation']


def test_a_visible_browser_keeps_its_own_user_agent(launches: list[Options]) -> None:
    build_driver(headless=False)
    (browser,) = launches

    assert not any(
        argument.startswith(('--headless', '--user-agent')) for argument in browser.arguments
    )


def _driver(user_agent: str) -> MagicMock:
    driver = MagicMock()
    driver.execute_script.side_effect = lambda script: (
        [{'brand': 'Chromium', 'version': '154'}] if 'userAgentData' in script else user_agent
    )
    driver.execute_async_script.return_value = {
        'architecture': 'arm',
        'bitness': '64',
        'model': 'a-model',
        'platform': 'macOS',
        'platformVersion': '15.6.0',
        'fullVersionList': [{'brand': 'Chromium', 'version': '154.0.7000.1'}],
        'mobile': True,
        'wow64': True,
    }
    return driver


def test_the_override_unmarks_the_user_agent_and_keeps_the_client_hints() -> None:
    driver = _driver(HEADLESS_USER_AGENT)

    assert mask_headless_user_agent(driver) == MASKED_USER_AGENT

    # Nothing else: with acceptLanguage, Chrome would send a malformed Accept-Language header
    driver.execute_cdp_cmd.assert_called_once_with(
        'Network.setUserAgentOverride',
        {
            'userAgent': MASKED_USER_AGENT,
            'userAgentMetadata': {
                'brands': [{'brand': 'Chromium', 'version': '154'}],
                'fullVersionList': [{'brand': 'Chromium', 'version': '154.0.7000.1'}],
                'platform': 'macOS',
                'platformVersion': '15.6.0',
                'architecture': 'arm',
                'model': 'a-model',
                'bitness': '64',
                'mobile': True,
                'wow64': True,
            },
        },
    )


def test_a_user_agent_already_unmarked_is_not_overridden() -> None:
    driver = _driver(MASKED_USER_AGENT)

    assert mask_headless_user_agent(driver) is None
    driver.execute_cdp_cmd.assert_not_called()
