"""Ctrl-C, whichever browser call or callback it lands in, reaches the caller."""

from __future__ import annotations

from collections.abc import Callable
from itertools import count
from pathlib import Path

import pytest
from selenium import webdriver
from selenium.common.exceptions import WebDriverException

from linkedin_jobs_scraper import login
from linkedin_jobs_scraper.config import Config
from linkedin_jobs_scraper.events import EventData, Events
from linkedin_jobs_scraper.linkedin_scraper import LinkedinScraper
from linkedin_jobs_scraper.strategies import authenticated_strategy
from linkedin_jobs_scraper.utils import chrome_driver, session
from linkedin_jobs_scraper.utils.job_record import RawJobDetails
from tests.unit.test_job_events import FakeDriver

JOB_ID = '4438239210'
USER_AGENT = 'Mozilla/5.0 HeadlessChrome/140.0.0.0 Safari/537.36'


class SignedInBrowser(FakeDriver):
    """A headless browser signed in to LinkedIn and showing the page of one job."""

    current_url = 'https://www.linkedin.com/jobs/'
    job_state: str | None = 'details'

    def __init__(self) -> None:
        super().__init__()
        self.opened: list[str] = []

    def set_page_load_timeout(self, _timeout: int) -> None:
        pass

    def get(self, url: str) -> None:
        self.opened.append(url)

    def execute_cdp_cmd(self, command: str, _params: object) -> object:
        if command == 'Target.getTargets':
            return {
                'targetInfos': [
                    {
                        'targetId': '1',
                        'type': 'page',
                        'attached': True,
                        'url': 'https://example.com/apply',
                    }
                ]
            }
        return {}

    def execute_async_script(self, _script: str, *_args: object) -> object:
        return {'platform': 'macOS'}

    def execute_script(self, script: str, *args: str) -> object:
        if script == 'return navigator.userAgent':
            return USER_AGENT
        if 'navigator.userAgentData' in script:
            return [{'brand': 'Chromium', 'version': '140'}]
        if script == authenticated_strategy.SINGLE_JOB_STATE_SCRIPT:
            return self.job_state
        if 'document.title' in script:
            return None
        return super().execute_script(script, *args)


class ApplyButtonBrowser(SignedInBrowser):
    """The job's apply button opens its external site in a second tab."""

    window_handles = ['main', 'apply']


class StillRenderingBrowser(SignedInBrowser):
    """The job's details are not rendered at the first reading."""

    readings = 0

    def read_details(self, job_id: str) -> RawJobDetails:
        self.readings += 1
        if self.readings == 1:
            raise WebDriverException('the document is being replaced')
        return super().read_details(job_id)


class UnrenderedJobBrowser(SignedInBrowser):
    """The job's page never renders."""

    job_state = None


class RememberedBrowser(SignedInBrowser):
    """LinkedIn issues the session once an authenticated route is opened."""

    def get_cookie(self, name: str) -> dict[str, str] | None:
        if name == 'li_at' and authenticated_strategy.FEED_URL not in self.opened:
            return None
        return super().get_cookie(name)


class EmptyJarBrowser(SignedInBrowser):
    """The session is the one the environment supplies."""

    def __init__(self) -> None:
        super().__init__()
        self.jar: dict[str, str] = {}

    def add_cookie(self, cookie: dict[str, str]) -> None:
        self.jar[cookie['name']] = cookie['value']

    def get_cookie(self, name: str) -> dict[str, str] | None:
        return {'name': name, 'value': self.jar[name]} if name in self.jar else None


class LeftLinkedinBrowser(SignedInBrowser):
    """The browser ends on an error page once the job has been read."""

    is_job_read = False

    def read_details(self, job_id: str) -> RawJobDetails:
        self.is_job_read = True
        return super().read_details(job_id)

    def execute_script(self, script: str, *args: str) -> object:
        if 'document.location.hostname' in script and self.is_job_read:
            return 'chromewebdata'
        return super().execute_script(script, *args)


class SignInPageBrowser(SignedInBrowser):
    """The profile holds no session until the person at the browser signs in."""

    cookie_reads = 0
    form_reads = 0

    def get_cookie(self, name: str) -> dict[str, str] | None:
        self.cookie_reads += 1
        return super().get_cookie(name) if self.cookie_reads > 2 else None

    def execute_script(self, script: str, *args: str) -> object:
        if '!!document.querySelector' in script:
            self.form_reads += 1
            return self.form_reads == 1
        return super().execute_script(script, *args)


class InterruptedCalls:
    """Raises KeyboardInterrupt on the call numbered `at`, counted over every browser it wraps."""

    def __init__(self, at: int) -> None:
        self.at = at
        self.calls = 0
        self.interrupted: str | None = None

    def count(self, name: str) -> None:
        self.calls += 1
        if self.calls == self.at:
            self.interrupted = name
            raise KeyboardInterrupt


class InterruptedBrowser:
    def __init__(self, calls: InterruptedCalls, browser: FakeDriver) -> None:
        self._calls = calls
        self._browser = browser

    def __getattr__(self, name: str) -> object:
        self._calls.count(name)
        return getattr(self._browser, name)


def _swallowed_interrupts(
    monkeypatch: pytest.MonkeyPatch,
    browser_type: type[FakeDriver],
    action: Callable[[], object],
) -> list[str]:
    """Run the action once per browser call it makes, interrupting that call, and list the calls
    where the interrupt did not come out of the action."""
    swallowed: list[str] = []
    for at in count(1):
        calls = InterruptedCalls(at)
        monkeypatch.setattr(
            webdriver, 'Chrome', lambda calls=calls, **_k: InterruptedBrowser(calls, browser_type())
        )
        # Looking up the User-Agent is cached for the whole process, and is part of the action
        monkeypatch.setattr(chrome_driver, '_is_user_agent_resolved', False)
        monkeypatch.setattr(chrome_driver, '_masked_user_agent', None)
        try:
            action()
        except KeyboardInterrupt:
            continue
        if calls.interrupted is None:
            assert at > 1, 'the action never called the browser'
            break
        swallowed.append(f'call {at}: {calls.interrupted}')
    return swallowed


@pytest.mark.parametrize(
    'browser_type',
    [
        SignedInBrowser,
        ApplyButtonBrowser,
        StillRenderingBrowser,
        UnrenderedJobBrowser,
        RememberedBrowser,
        EmptyJarBrowser,
        LeftLinkedinBrowser,
    ],
)
def test_ctrl_c_stops_a_single_job_scrape(
    monkeypatch: pytest.MonkeyPatch, browser_type: type[SignedInBrowser]
) -> None:
    monkeypatch.setattr(Config, 'LI_AT_COOKIE', 'session-value')
    monkeypatch.setattr(authenticated_strategy, 'sleep', lambda _seconds: None)
    monkeypatch.setattr(session, 'sleep', lambda _seconds: None)
    monkeypatch.setattr(authenticated_strategy, 'SINGLE_JOB_PANEL_TIMEOUT', 0.2)
    errors: list[str] = []

    def scrape() -> None:
        scraper = LinkedinScraper(chrome_executable_path='/chromedriver')
        scraper.on(Events.ERROR, lambda error: errors.append(error))
        scraper.scrape_job(JOB_ID, apply_link=True)

    assert _swallowed_interrupts(monkeypatch, browser_type, scrape) == []
    assert errors == []


def test_ctrl_c_stops_a_login(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(login, 'sleep', lambda _seconds: None)

    def sign_in() -> None:
        login.sign_in(tmp_path / 'profile', executable_path='/chromedriver')

    assert _swallowed_interrupts(monkeypatch, SignInPageBrowser, sign_in) == []


def test_a_login_interrupted_while_the_browser_closes_leaves_no_empty_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class ClosedWindowBrowser(SignedInBrowser):
        window_handles: list[str] = []

        def quit(self) -> None:
            raise KeyboardInterrupt

    monkeypatch.setattr(login, 'sleep', lambda _seconds: None)
    monkeypatch.setattr(webdriver, 'Chrome', lambda **_k: ClosedWindowBrowser())

    with pytest.raises(KeyboardInterrupt):
        login.sign_in(tmp_path / 'profile', executable_path='/chromedriver')

    assert not (tmp_path / 'profile').exists()


def test_ctrl_c_stops_the_check_for_credentials_before_a_login(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(login, 'sleep', lambda _seconds: None)

    def has_credentials() -> None:
        login.has_credentials(tmp_path, executable_path='/chromedriver')

    assert _swallowed_interrupts(monkeypatch, SignedInBrowser, has_credentials) == []


@pytest.mark.parametrize('exception', [KeyboardInterrupt, SystemExit])
def test_a_callback_stops_a_single_job_scrape_by_interrupting_or_exiting(
    monkeypatch: pytest.MonkeyPatch, exception: type[BaseException]
) -> None:
    monkeypatch.setattr(Config, 'LI_AT_COOKIE', 'session-value')
    monkeypatch.setattr(authenticated_strategy, 'sleep', lambda _seconds: None)
    monkeypatch.setattr(webdriver, 'Chrome', lambda **_k: SignedInBrowser())
    scraper = LinkedinScraper(chrome_executable_path='/chromedriver')

    def stopping_callback(_data: EventData) -> None:
        raise exception

    scraper.on(Events.DATA, stopping_callback)

    with pytest.raises(exception):
        scraper.scrape_job(JOB_ID)
