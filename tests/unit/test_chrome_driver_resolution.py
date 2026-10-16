"""Offline tests for chromedriver resolution through Selenium Manager.

No network, no browser: SeleniumManager, ChromeService and webdriver.Chrome are mocked.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from selenium.common.exceptions import WebDriverException

from linkedin_jobs_scraper.exceptions import ChromedriverResolutionException
from linkedin_jobs_scraper.utils import chrome_driver
from linkedin_jobs_scraper.utils.chrome_driver import (
    CHROMEDRIVER_RESOLUTION_HINT,
    ChromedriverPaths,
    build_driver,
    resolve_chromedriver_paths,
    resolve_masked_user_agent,
)

HEADLESS_USER_AGENT = 'Mozilla/5.0 HeadlessChrome/155.0.0.0 Safari/537.36'


@pytest.fixture
def binaries(tmp_path: Path) -> ChromedriverPaths:
    driver_path = tmp_path / 'chromedriver'
    browser_path = tmp_path / 'chrome'
    driver_path.write_text('')
    browser_path.write_text('')
    return ChromedriverPaths(driver_path=str(driver_path), browser_path=str(browser_path))


@pytest.fixture
def selenium_manager(monkeypatch, binaries: ChromedriverPaths) -> MagicMock:
    manager = MagicMock()
    manager.return_value.binary_paths.return_value = binaries._asdict()
    monkeypatch.setattr(chrome_driver, 'SeleniumManager', manager)
    return manager


@pytest.fixture
def chrome_service(monkeypatch) -> MagicMock:
    service = MagicMock()
    monkeypatch.setattr(chrome_driver, 'ChromeService', service)
    return service


@pytest.fixture
def chrome(monkeypatch) -> MagicMock:
    chrome = MagicMock()
    chrome.return_value.execute_script.return_value = HEADLESS_USER_AGENT
    monkeypatch.setattr(chrome_driver.webdriver, 'Chrome', chrome)
    return chrome


@pytest.fixture(autouse=True)
def reset_user_agent_cache(monkeypatch):
    monkeypatch.setattr(chrome_driver, '_masked_user_agent', None)
    monkeypatch.setattr(chrome_driver, '_is_user_agent_resolved', False)


def _sent_args(selenium_manager: MagicMock) -> list[str]:
    return selenium_manager.return_value.binary_paths.call_args.args[0]


def test_resolution_skips_driver_in_path(selenium_manager, binaries):
    paths = resolve_chromedriver_paths()

    args = _sent_args(selenium_manager)
    assert args[:2] == ['--browser', 'chrome']
    assert '--skip-driver-in-path' in args
    assert '--browser-path' not in args
    assert paths == binaries


def test_resolution_passes_browser_path_when_binary_location_is_set(selenium_manager):
    resolve_chromedriver_paths('/opt/chrome/chrome')

    args = _sent_args(selenium_manager)
    assert '--skip-driver-in-path' in args
    index = args.index('--browser-path')
    assert args[index + 1] == '/opt/chrome/chrome'


def test_resolution_failure_is_wrapped_with_hint(selenium_manager):
    cause = WebDriverException('Unable to obtain driver for chrome')
    selenium_manager.return_value.binary_paths.side_effect = cause

    with pytest.raises(ChromedriverResolutionException) as excinfo:
        resolve_chromedriver_paths()

    message = str(excinfo.value)
    assert 'Unable to obtain driver for chrome' in message
    assert CHROMEDRIVER_RESOLUTION_HINT in message
    assert '--chrome-executable-path' in message
    assert 'chrome_executable_path=' in message
    assert excinfo.value.__cause__ is cause


@pytest.mark.parametrize('missing_key', ['driver_path', 'browser_path'])
def test_resolution_rejects_nonexistent_paths(selenium_manager, binaries, missing_key):
    output = binaries._asdict()
    output[missing_key] = '/nonexistent/binary'
    selenium_manager.return_value.binary_paths.return_value = output

    with pytest.raises(ChromedriverResolutionException) as excinfo:
        resolve_chromedriver_paths()

    message = str(excinfo.value)
    assert '/nonexistent/binary' in message
    assert 'is not a file' in message
    assert CHROMEDRIVER_RESOLUTION_HINT in message
    assert isinstance(excinfo.value.__cause__, ValueError)


@pytest.mark.parametrize('returned_value', [None, ''])
def test_resolution_names_missing_driver_for_installed_chrome(selenium_manager, returned_value):
    selenium_manager.return_value.binary_paths.return_value = {
        'driver_path': returned_value, 'browser_path': returned_value}

    with pytest.raises(ChromedriverResolutionException) as excinfo:
        resolve_chromedriver_paths()

    message = str(excinfo.value)
    assert message.startswith('Selenium Manager returned no chromedriver for the installed Chrome')
    assert CHROMEDRIVER_RESOLUTION_HINT in message
    assert isinstance(excinfo.value.__cause__, ValueError)


def test_resolution_names_missing_driver_for_requested_chrome(selenium_manager):
    selenium_manager.return_value.binary_paths.return_value = {'driver_path': '', 'browser_path': ''}

    with pytest.raises(ChromedriverResolutionException) as excinfo:
        resolve_chromedriver_paths('/nonexistent/chrome')

    assert str(excinfo.value).startswith(
        'Selenium Manager returned no chromedriver for Chrome at /nonexistent/chrome')


def test_resolution_names_missing_browser_path(selenium_manager, binaries):
    selenium_manager.return_value.binary_paths.return_value = {
        'driver_path': binaries.driver_path, 'browser_path': ''}

    with pytest.raises(ChromedriverResolutionException) as excinfo:
        resolve_chromedriver_paths()

    message = str(excinfo.value)
    assert message.startswith('Selenium Manager returned no Chrome browser path for the installed Chrome')
    assert CHROMEDRIVER_RESOLUTION_HINT in message


def test_build_driver_uses_resolved_driver_and_browser(selenium_manager, chrome_service, chrome, binaries):
    build_driver(headless=False)

    chrome_service.assert_called_once_with(binaries.driver_path)
    options = chrome.call_args.kwargs['options']
    assert options.binary_location == binaries.browser_path
    assert chrome.call_args.kwargs['service'] is chrome_service.return_value
    assert '--skip-driver-in-path' in _sent_args(selenium_manager)


def test_build_driver_keeps_user_binary_location(selenium_manager, chrome_service, chrome):
    build_driver(binary_location='/opt/chrome/chrome', headless=False)

    args = _sent_args(selenium_manager)
    assert args[args.index('--browser-path') + 1] == '/opt/chrome/chrome'
    assert chrome.call_args.kwargs['options'].binary_location == '/opt/chrome/chrome'


def test_build_driver_uses_explicit_executable_path_verbatim(selenium_manager, chrome_service, chrome):
    build_driver(executable_path='/usr/local/bin/chromedriver', headless=True)

    selenium_manager.assert_not_called()
    assert chrome_service.call_count == 2
    for call in chrome_service.call_args_list:
        assert call.args == ('/usr/local/bin/chromedriver',)


def test_build_driver_propagates_resolution_failure(selenium_manager, chrome_service, chrome):
    selenium_manager.return_value.binary_paths.side_effect = WebDriverException('boom')

    with pytest.raises(ChromedriverResolutionException):
        build_driver(headless=True)

    chrome.assert_not_called()


def test_resolve_masked_user_agent_uses_resolved_driver(selenium_manager, chrome_service, chrome, binaries):
    user_agent = resolve_masked_user_agent()

    assert user_agent == 'Mozilla/5.0 Chrome/155.0.0.0 Safari/537.36'
    chrome_service.assert_called_once_with(binaries.driver_path)
    assert chrome.call_args.kwargs['options'].binary_location == binaries.browser_path
    assert '--skip-driver-in-path' in _sent_args(selenium_manager)


def test_resolve_masked_user_agent_uses_explicit_executable_path(selenium_manager, chrome_service, chrome):
    resolve_masked_user_agent(executable_path='/usr/local/bin/chromedriver')

    selenium_manager.assert_not_called()
    chrome_service.assert_called_once_with('/usr/local/bin/chromedriver')
