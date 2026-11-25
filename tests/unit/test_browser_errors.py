"""A browser that fails is tolerated where nothing depends on its answer. A bug in this package is
never mistaken for that."""

from __future__ import annotations

from collections.abc import Callable
from http.client import BadStatusLine, RemoteDisconnected
from itertools import count
from pathlib import Path

import pytest
from selenium import webdriver
from selenium.common.exceptions import InvalidSessionIdException
from urllib3.connectionpool import HTTPConnectionPool
from urllib3.exceptions import MaxRetryError, ProtocolError

from linkedin_jobs_scraper import login
from linkedin_jobs_scraper.config import Config
from linkedin_jobs_scraper.events import EventData, Events
from linkedin_jobs_scraper.exceptions import InvalidCookieException
from linkedin_jobs_scraper.linkedin_scraper import LinkedinScraper
from linkedin_jobs_scraper.query import Query, QueryOptions
from linkedin_jobs_scraper.strategies import authenticated_strategy
from linkedin_jobs_scraper.utils import chrome_driver, session

from .test_interrupts import (
    JOB_ID,
    ApplyButtonBrowser,
    EmptyJarBrowser,
    LeftLinkedinBrowser,
    RememberedBrowser,
    SignedInBrowser,
    SignInPageBrowser,
    StillRenderingBrowser,
    TwoTabsBrowser,
    UnrenderedJobBrowser,
)
from .test_job_events import FakeDriver


def bug() -> Exception:
    return AttributeError('bug in the package')


def chrome_is_gone() -> Exception:
    return InvalidSessionIdException('invalid session id')


def chromedriver_is_gone() -> Exception:
    return MaxRetryError(HTTPConnectionPool('localhost'), '/session', ConnectionRefusedError())


def chromedriver_goes_away_while_answering() -> Exception:
    return ProtocolError('Connection aborted.', RemoteDisconnected(''))


BROWSER_FAILURES = [chrome_is_gone, chromedriver_is_gone, chromedriver_goes_away_while_answering]

Failure = Callable[[], Exception]


class FailingCall:
    """Raises the failure on the call numbered `at`, counted over every browser it wraps."""

    def __init__(self, at: int, failure: Failure) -> None:
        self.at = at
        self.failure = failure
        self.calls = 0
        self.failed: str | None = None

    def count(self, name: str) -> None:
        self.calls += 1
        if self.calls == self.at:
            self.failed = name
            raise self.failure()


class FailingBrowser:
    def __init__(self, call: FailingCall, browser: FakeDriver) -> None:
        self._call = call
        self._browser = browser

    def __getattr__(self, name: str) -> object:
        self._call.count(name)
        return getattr(self._browser, name)


@pytest.fixture(autouse=True)
def _no_waiting_and_one_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, 'LI_AT_COOKIE', 'session-value')
    monkeypatch.setattr(Config, 'LI_RM_COOKIE', None)
    monkeypatch.setattr(Config, 'LI_BCOOKIE', None)
    for module in (authenticated_strategy, session, login):
        monkeypatch.setattr(module, 'sleep', lambda _seconds: None)
    monkeypatch.setattr(authenticated_strategy, 'SINGLE_JOB_PANEL_TIMEOUT', 0.2)


def _outcomes(
    monkeypatch: pytest.MonkeyPatch,
    browser_type: type[FakeDriver],
    failure: Failure,
    action: Callable[[], str],
) -> list[tuple[str, str]]:
    """Run the action once per browser call it makes, failing that call. List the failed call and
    what came of the action: what it returned, or 'raised'."""
    outcomes: list[tuple[str, str]] = []
    for at in count(1):
        call = FailingCall(at, failure)
        monkeypatch.setattr(
            webdriver, 'Chrome', lambda call=call, **_k: FailingBrowser(call, browser_type())
        )
        # Looking up the User-Agent is cached for the whole process, and is part of the action
        monkeypatch.setattr(chrome_driver, '_is_user_agent_resolved', False)
        monkeypatch.setattr(chrome_driver, '_masked_user_agent', None)
        try:
            outcome = action()
        except type(failure()):
            outcome = 'raised'
        if call.failed is None:
            assert at > 1, 'the action never called the browser'
            break
        outcomes.append((call.failed, outcome))
    return outcomes


def _outcome(scrape: Callable[[LinkedinScraper], None]) -> str:
    errors: list[str] = []
    scraper = LinkedinScraper(chrome_executable_path='/chromedriver')
    scraper.on(Events.ERROR, errors.append)
    try:
        scrape(scraper)
    except InvalidCookieException:
        return 'no session'
    return 'ERROR' if errors else 'no ERROR'


def _scrape_job() -> str:
    return _outcome(lambda scraper: scraper.scrape_job(JOB_ID, apply_link=True))


def _search() -> str:
    options = QueryOptions(locations=['103350119'], limit=1, apply_link=True)
    return _outcome(lambda scraper: scraper.run(Query(query='engineer', options=options)))


SINGLE_JOB_BROWSERS = [
    SignedInBrowser,
    ApplyButtonBrowser,
    StillRenderingBrowser,
    UnrenderedJobBrowser,
    RememberedBrowser,
    EmptyJarBrowser,
    LeftLinkedinBrowser,
]


@pytest.mark.parametrize('browser_type', SINGLE_JOB_BROWSERS)
def test_a_bug_at_any_browser_call_of_a_single_job_scrape_is_an_error_event(
    monkeypatch: pytest.MonkeyPatch, browser_type: type[FakeDriver]
) -> None:
    outcomes = _outcomes(monkeypatch, browser_type, bug, _scrape_job)

    assert {outcome for _call, outcome in outcomes} == {'ERROR'}


@pytest.mark.parametrize('browser_type', [SignedInBrowser, TwoTabsBrowser, EmptyJarBrowser])
def test_a_bug_at_any_browser_call_of_a_search_is_an_error_event(
    monkeypatch: pytest.MonkeyPatch, browser_type: type[FakeDriver]
) -> None:
    outcomes = _outcomes(monkeypatch, browser_type, bug, _search)

    assert {outcome for _call, outcome in outcomes} == {'ERROR'}


@pytest.mark.parametrize('failure', BROWSER_FAILURES)
@pytest.mark.parametrize('browser_type', SINGLE_JOB_BROWSERS)
def test_a_failed_browser_probe_of_a_single_job_scrape_is_no_error_event(
    monkeypatch: pytest.MonkeyPatch, browser_type: type[FakeDriver], failure: Failure
) -> None:
    outcomes = _outcomes(monkeypatch, browser_type, failure, _scrape_job)

    error_calls = {call for call, outcome in outcomes if outcome == 'ERROR'}
    assert error_calls == {'set_page_load_timeout', 'get'}


@pytest.mark.parametrize('failure', BROWSER_FAILURES)
def test_a_failed_browser_probe_of_a_search_is_no_error_event(
    monkeypatch: pytest.MonkeyPatch, failure: Failure
) -> None:
    outcomes = _outcomes(monkeypatch, TwoTabsBrowser, failure, _search)

    error_calls = {call for call, outcome in outcomes if outcome == 'ERROR'}
    assert error_calls == {
        'set_page_load_timeout',
        'get',
        # Reading the handles and going back to the first one
        'window_handles',
        'switch_to',
        # Reading the card, and clicking it
        'execute_script',
    }
    # The applied location too: the location picker tolerates Selenium's own errors only
    script_outcomes = [outcome for call, outcome in outcomes if call == 'execute_script']
    assert script_outcomes.count('ERROR') <= 3


@pytest.mark.parametrize(
    'failure',
    [*BROWSER_FAILURES, ConnectionResetError, RemoteDisconnected, lambda: BadStatusLine('')],
)
def test_a_browser_that_fails_to_close_is_no_error_event(
    monkeypatch: pytest.MonkeyPatch, failure: Failure
) -> None:
    class UnclosableBrowser(SignedInBrowser):
        def quit(self) -> None:
            raise failure()

    monkeypatch.setattr(webdriver, 'Chrome', lambda **_k: UnclosableBrowser())

    assert _scrape_job() == 'no ERROR'
    assert _search() == 'no ERROR'


@pytest.mark.parametrize('failure', [*BROWSER_FAILURES, OSError])
def test_a_browser_that_does_not_start_leaves_the_user_agent_unmasked(
    monkeypatch: pytest.MonkeyPatch, failure: Failure
) -> None:
    def fail_to_start(**_kwargs: object) -> None:
        raise failure()

    monkeypatch.setattr(webdriver, 'Chrome', fail_to_start)
    monkeypatch.setattr(chrome_driver, '_is_user_agent_resolved', False)
    monkeypatch.setattr(chrome_driver, '_masked_user_agent', None)

    assert chrome_driver.resolve_masked_user_agent('/chromedriver') is None


UNDESCRIBED_TAB = {'type': 'page', 'attached': True, 'targetId': '2'}


# Two tabs, so that the search takes one for a leftover to close
@pytest.mark.parametrize(
    'targets',
    [
        [UNDESCRIBED_TAB, UNDESCRIBED_TAB],
        [{**UNDESCRIBED_TAB, 'url': 1}, {**UNDESCRIBED_TAB, 'url': 1}],
        [None, None],
        'ab',
        None,
    ],
)
def test_tabs_chrome_does_not_describe_cost_the_apply_link_and_not_the_job(
    monkeypatch: pytest.MonkeyPatch, targets: object
) -> None:
    class UndescribedTabBrowser(TwoTabsBrowser):
        def execute_cdp_cmd(self, command: str, _params: object) -> object:
            return {'targetInfos': targets} if command == 'Target.getTargets' else {}

    monkeypatch.setattr(webdriver, 'Chrome', lambda **_k: UndescribedTabBrowser())
    delivered: list[EventData] = []
    errors: list[str] = []
    scraper = LinkedinScraper(chrome_executable_path='/chromedriver')
    scraper.on(Events.DATA, delivered.append)
    scraper.on(Events.ERROR, errors.append)

    scraper.scrape_job(JOB_ID, apply_link=True)
    options = QueryOptions(locations=['103350119'], limit=1, apply_link=True)
    scraper.run(Query(query='engineer', options=options))

    assert errors == []
    assert [data.apply_link for data in delivered] == ['', '']


def test_windows_selenium_does_not_list_cost_the_apply_link_and_not_the_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnlistedWindowsBrowser(SignedInBrowser):
        def __getattribute__(self, name: str) -> object:
            return None if name == 'window_handles' else super().__getattribute__(name)

    monkeypatch.setattr(webdriver, 'Chrome', lambda **_k: UnlistedWindowsBrowser())
    delivered: list[EventData] = []
    scraper = LinkedinScraper(chrome_executable_path='/chromedriver')
    scraper.on(Events.DATA, delivered.append)

    scraper.scrape_job(JOB_ID, apply_link=True)

    assert [data.apply_link for data in delivered] == ['']


def test_a_type_error_while_looking_for_the_apply_link_is_an_error_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BuggyTabsBrowser(ApplyButtonBrowser):
        def execute_cdp_cmd(self, command: str, params: object) -> object:
            if command == 'Target.getTargets':
                raise TypeError('bug in the package')
            return super().execute_cdp_cmd(command, params)

    monkeypatch.setattr(webdriver, 'Chrome', lambda **_k: BuggyTabsBrowser())
    delivered: list[EventData] = []
    errors: list[str] = []
    scraper = LinkedinScraper(chrome_executable_path='/chromedriver')
    scraper.on(Events.DATA, delivered.append)
    scraper.on(Events.ERROR, errors.append)

    scraper.scrape_job(JOB_ID, apply_link=True)

    assert delivered == []
    assert len(errors) == 1
    assert 'bug in the package' in errors[0]


def test_a_tab_chrome_does_not_describe_is_not_read_past_the_one_looked_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = {**UNDESCRIBED_TAB, 'url': 'https://example.com/apply'}

    class ApplicationTabBrowser(TwoTabsBrowser):
        def execute_cdp_cmd(self, command: str, _params: object) -> object:
            return {'targetInfos': [{'attached': False}, application, {}]}

    monkeypatch.setattr(webdriver, 'Chrome', lambda **_k: ApplicationTabBrowser())
    delivered: list[EventData] = []
    scraper = LinkedinScraper(chrome_executable_path='/chromedriver')
    scraper.on(Events.DATA, delivered.append)

    scraper.scrape_job(JOB_ID, apply_link=True)

    assert [data.apply_link for data in delivered] == ['https://example.com/apply']


def test_a_bug_at_any_browser_call_of_a_login_reaches_the_caller(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def sign_in() -> str:
        return str(login.sign_in(tmp_path / 'profile', executable_path='/chromedriver'))

    outcomes = _outcomes(monkeypatch, SignInPageBrowser, bug, sign_in)

    assert {outcome for _call, outcome in outcomes} == {'raised'}


def test_a_bug_at_any_browser_call_of_the_check_for_credentials_reaches_the_caller(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def has_credentials() -> str:
        return str(login.has_credentials(tmp_path, executable_path='/chromedriver'))

    outcomes = _outcomes(monkeypatch, SignedInBrowser, bug, has_credentials)

    assert {outcome for _call, outcome in outcomes} == {'raised'}


@pytest.mark.parametrize('failure', BROWSER_FAILURES)
def test_a_failed_browser_probe_of_a_login_is_tolerated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: Failure
) -> None:
    def sign_in() -> str:
        return str(login.sign_in(tmp_path / 'profile', executable_path='/chromedriver'))

    def has_credentials() -> str:
        return str(login.has_credentials(tmp_path, executable_path='/chromedriver'))

    login_outcomes = _outcomes(monkeypatch, SignInPageBrowser, failure, sign_in)
    check_outcomes = _outcomes(monkeypatch, SignedInBrowser, failure, has_credentials)

    assert {call for call, outcome in login_outcomes if outcome == 'raised'} == {
        'set_page_load_timeout',
        'get',
    }
    assert {call for call, outcome in check_outcomes if outcome == 'raised'} == {
        'set_page_load_timeout'
    }
