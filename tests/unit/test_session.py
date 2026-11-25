"""How a run gets a LinkedIn session, keeps it, and gives up on it."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from selenium.common.exceptions import InvalidCookieDomainException, WebDriverException

from linkedin_jobs_scraper.config import Config
from linkedin_jobs_scraper.events import EventMetrics, Events
from linkedin_jobs_scraper.exceptions import InvalidCookieException
from linkedin_jobs_scraper.linkedin_scraper import LinkedinScraper
from linkedin_jobs_scraper.query import Query, QueryOptions
from linkedin_jobs_scraper.strategies import authenticated_strategy
from linkedin_jobs_scraper.utils import session as session_module
from linkedin_jobs_scraper.utils.job_record import RawJobRecord

from .test_job_events import JOB_IDS, FakeDriver, scraper_module

Cookie = dict[str, str | int]

YEAR = 365 * 24 * 60 * 60


class LinkedinBrowser(FakeDriver):
    """A browser, and the sessions LinkedIn accepts from it or issues to it.

    A page of results renders only with an accepted session. Without one, or with a retired one,
    LinkedIn shows its logged out page.
    """

    def __init__(
        self,
        jar: dict[str, str] | None = None,
        accepted: tuple[str, ...] = (),
        remembered: tuple[str, str] | None = None,
        issued: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        self.jar: dict[str, Cookie] = {
            name: {'name': name, 'value': value} for name, value in (jar or {}).items()
        }
        self.accepted = set(accepted)
        self.remembered = remembered
        self.issued = iter(issued)
        self.opened: list[str] = []
        self.added: list[Cookie] = []
        self.deleted: list[str] = []
        self.before_search: Callable[[int], None] = lambda _number: None
        self.before_card: Callable[[str], None] = lambda _job_id: None
        self.is_error_page = False

    @property
    def searches(self) -> int:
        return len([url for url in self.opened if '/jobs/search' in url])

    @property
    def _is_signed_in(self) -> bool:
        return 'li_at' in self.jar and self.jar['li_at']['value'] in self.accepted

    def get(self, url: str) -> None:
        self.opened.append(url)
        self.is_error_page = False
        if '/jobs/search' in url:
            self.before_search(self.searches)
        pair = tuple(
            self.jar[name]['value'] if name in self.jar else '' for name in ('li_rm', 'bcookie')
        )
        if url == authenticated_strategy.FEED_URL and pair == self.remembered:
            session = next(self.issued, None)
            if session is not None:
                self.accepted.add(session)
                self.jar['li_at'] = {'name': 'li_at', 'value': session}

    def get_cookie(self, name: str) -> Cookie | None:
        return None if self.is_error_page else self.jar.get(name)

    def add_cookie(self, cookie: Cookie) -> None:
        if self.is_error_page:
            raise InvalidCookieDomainException('invalid cookie domain')
        self.added.append(cookie)
        self.jar[str(cookie['name'])] = cookie

    def delete_cookie(self, name: str) -> None:
        self.deleted.append(name)
        self.jar.pop(name, None)

    def execute_script(self, script: str, *args: str) -> object:
        if 'document.location.hostname' in script:
            return 'chromewebdata' if self.is_error_page else 'www.linkedin.com'
        if '!document.querySelector(arguments[0]) &&' in script:
            return not self.is_error_page and not self._is_signed_in
        if 'performance.timeOrigin' in script:
            return None
        if 'document.title' in script:
            return None
        if 'responseStatus' in script:
            return 429 if self.is_error_page else 200
        if self.is_error_page or not self._is_signed_in:
            return None
        return super().execute_script(script, *args)

    def read_card(self, job_id: str) -> RawJobRecord:
        self.before_card(job_id)
        return super().read_card(job_id)


@dataclass
class Outcome:
    job_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    refreshed: list[str] = field(default_factory=list)
    metrics: list[EventMetrics] = field(default_factory=list)
    invalid_sessions: int = 0
    error: InvalidCookieException | None = None


Run = Callable[..., Outcome]


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Run:
    """Search for the two jobs of `JOB_IDS` with a browser and the cookies of the environment."""
    profile = tmp_path / 'profile'
    profile.mkdir()
    (profile / 'Local State').write_text('{}')
    for module in (authenticated_strategy, session_module):
        monkeypatch.setattr(module, 'sleep', lambda _seconds: None)

    def run_search(
        browser: LinkedinBrowser,
        *,
        has_profile: bool = False,
        li_at: str | None = None,
        li_rm: str | None = None,
        bcookie: str | None = None,
    ) -> Outcome:
        monkeypatch.setattr(Config, 'LI_AT_COOKIE', li_at)
        monkeypatch.setattr(Config, 'LI_RM_COOKIE', li_rm)
        monkeypatch.setattr(Config, 'LI_BCOOKIE', bcookie)
        monkeypatch.setattr(scraper_module, 'build_driver', lambda *_a, **_k: browser)

        outcome = Outcome()

        def on_invalid_session() -> None:
            outcome.invalid_sessions += 1

        scraper = LinkedinScraper(chrome_user_data_dir=str(profile) if has_profile else None)
        scraper.on(Events.DATA, lambda data: outcome.job_ids.append(data.job_id))
        scraper.on(Events.ERROR, outcome.errors.append)
        scraper.on(Events.METRICS, outcome.metrics.append)
        scraper.on(Events.INVALID_SESSION, on_invalid_session)
        scraper.on(
            Events.SESSION_REFRESHED, lambda session: outcome.refreshed.append(session.li_at)
        )
        options = QueryOptions(locations=['103350119'], limit=len(JOB_IDS))
        try:
            scraper.run(Query(query='engineer', options=options))
        except InvalidCookieException as e:
            outcome.error = e
        return outcome

    return run_search


def test_the_session_of_a_profile_wins_over_the_supplied_credentials(run: Run) -> None:
    browser = LinkedinBrowser(jar={'li_at': 'profile'}, accepted=('profile', 'supplied'))
    outcome = run(browser, has_profile=True, li_at='supplied', li_rm='rm', bcookie='b')

    assert outcome.job_ids == JOB_IDS
    assert browser.added == []
    assert authenticated_strategy.FEED_URL not in browser.opened


def test_a_supplied_session_cookie_is_injected_for_the_domain_linkedin_uses(run: Run) -> None:
    browser = LinkedinBrowser(accepted=('supplied',))
    outcome = run(browser, li_at='supplied')

    assert outcome.job_ids == JOB_IDS
    assert browser.added == [{'name': 'li_at', 'value': 'supplied', 'domain': '.www.linkedin.com'}]
    assert outcome.refreshed == []


def test_a_remember_me_pair_is_exchanged_for_a_session_that_is_reported(run: Run) -> None:
    browser = LinkedinBrowser(remembered=('rm', 'b'), issued=('issued',))
    outcome = run(browser, li_rm='rm', bcookie='b', li_at='supplied')

    assert outcome.job_ids == JOB_IDS
    assert outcome.refreshed == ['issued']
    assert [(cookie['name'], cookie['value'], cookie['domain']) for cookie in browser.added] == [
        ('li_rm', 'rm', '.www.linkedin.com'),
        ('bcookie', 'b', '.linkedin.com'),
    ]


def test_an_injected_pair_is_kept_for_a_year(run: Run) -> None:
    browser = LinkedinBrowser(remembered=('rm', 'b'), issued=('issued',))
    run(browser, li_rm='rm', bcookie='b')

    assert [cookie['expiry'] for cookie in browser.added] == [
        pytest.approx(time.time() + YEAR, abs=60),
        pytest.approx(time.time() + YEAR, abs=60),
    ]


def test_the_pair_of_a_profile_is_never_overwritten(run: Run) -> None:
    browser = LinkedinBrowser(
        jar={'li_rm': 'own', 'bcookie': 'own-b'}, remembered=('own', 'own-b'), issued=('issued',)
    )
    outcome = run(browser, has_profile=True, li_rm='rm', bcookie='b')

    assert outcome.job_ids == JOB_IDS
    assert browser.added == []


@pytest.mark.parametrize('half', [{'li_rm': 'rm'}, {'bcookie': 'b'}])
def test_half_a_pair_is_not_injected(run: Run, half: dict[str, str]) -> None:
    browser = LinkedinBrowser(accepted=('supplied',))
    outcome = run(browser, li_at='supplied', **half)

    assert outcome.job_ids == JOB_IDS
    assert [cookie['name'] for cookie in browser.added] == ['li_at']
    assert authenticated_strategy.FEED_URL not in browser.opened


@pytest.mark.parametrize('has_profile', [True, False])
def test_a_refused_pair_falls_back_to_the_supplied_session(run: Run, has_profile: bool) -> None:
    browser = LinkedinBrowser(accepted=('supplied',))
    outcome = run(browser, has_profile=has_profile, li_rm='rm', bcookie='b', li_at='supplied')

    assert outcome.job_ids == JOB_IDS
    assert [cookie['name'] for cookie in browser.added] == ['li_rm', 'bcookie', 'li_at']


def test_a_refused_pair_with_nothing_to_fall_back_on_ends_the_run(run: Run) -> None:
    browser = LinkedinBrowser()
    outcome = run(browser, li_rm='rm', bcookie='b')

    assert outcome.error is not None
    assert outcome.invalid_sessions == 1
    assert browser.searches == 0


def test_a_session_linkedin_clears_is_rebuilt_and_the_page_opened_again(run: Run) -> None:
    browser = LinkedinBrowser(
        jar={'li_at': 'retired', 'li_rm': 'rm', 'bcookie': 'b'},
        remembered=('rm', 'b'),
        issued=('issued',),
    )

    def clear_retired_session(_number: int) -> None:
        if browser.jar.get('li_at', {}).get('value') == 'retired':
            del browser.jar['li_at']

    browser.before_search = clear_retired_session
    outcome = run(browser, has_profile=True)

    assert outcome.job_ids == JOB_IDS
    assert outcome.refreshed == ['issued']
    assert outcome.invalid_sessions == 0
    assert browser.searches == 2


def test_a_refused_session_left_in_the_jar_is_removed_before_signing_in_again(run: Run) -> None:
    browser = LinkedinBrowser(jar={'li_at': 'retired'}, accepted=('supplied',))
    outcome = run(browser, has_profile=True, li_at='supplied')

    assert outcome.job_ids == JOB_IDS
    assert browser.deleted == ['li_at']
    assert browser.searches == 2


def test_the_refused_session_is_not_taken_for_the_one_linkedin_issues(run: Run) -> None:
    browser = LinkedinBrowser(
        jar={'li_at': 'retired', 'li_rm': 'rm', 'bcookie': 'b'}, accepted=('supplied',)
    )
    outcome = run(browser, has_profile=True, li_at='supplied')

    assert outcome.job_ids == JOB_IDS
    assert [cookie['value'] for cookie in browser.added] == ['supplied']


def test_a_session_cleared_again_after_signing_in_again_ends_the_run(run: Run) -> None:
    browser = LinkedinBrowser()

    def clear_session(_number: int) -> None:
        browser.jar.pop('li_at', None)

    browser.before_search = clear_session
    outcome = run(browser, li_at='retired')

    assert outcome.error is not None
    assert outcome.invalid_sessions == 1
    assert browser.searches == 2


def test_a_throttled_page_says_nothing_about_the_session(run: Run) -> None:
    browser = LinkedinBrowser(accepted=('supplied',))

    def throttle(_number: int) -> None:
        browser.is_error_page = True

    browser.before_search = throttle
    outcome = run(browser, li_at='supplied')

    assert outcome.error is None
    assert outcome.invalid_sessions == 0
    assert browser.deleted == []
    assert [cookie['name'] for cookie in browser.added] == ['li_at']


def test_a_throttled_page_is_opened_again_with_the_same_session(run: Run) -> None:
    browser = LinkedinBrowser(accepted=('supplied',))

    def throttle_once(number: int) -> None:
        browser.is_error_page = number == 1

    browser.before_search = throttle_once
    outcome = run(browser, li_at='supplied')

    assert outcome.job_ids == JOB_IDS
    assert [cookie['name'] for cookie in browser.added] == ['li_at']


def test_a_session_lost_part_way_is_rebuilt_without_delivering_a_job_twice(run: Run) -> None:
    browser = LinkedinBrowser(accepted=('supplied',))
    losses = iter([True])

    def lose_session_once(job_id: str) -> None:
        if job_id == JOB_IDS[1] and next(losses, False):
            del browser.jar['li_at']
            raise WebDriverException('the document is being replaced')

    browser.before_card = lose_session_once
    outcome = run(browser, li_at='supplied')

    assert outcome.job_ids == JOB_IDS
    assert len(outcome.errors) == 1
    assert outcome.invalid_sessions == 0
    # The page without a session, then the same page with the new one
    assert browser.searches == 1 + 2


def test_the_jobs_left_when_a_session_is_lost_are_retried_and_not_failed(run: Run) -> None:
    browser = LinkedinBrowser(accepted=('supplied',))
    losses = iter([True])

    def lose_session_once(_job_id: str) -> None:
        if next(losses, False):
            del browser.jar['li_at']
            raise WebDriverException('the document is being replaced')

    browser.before_card = lose_session_once
    outcome = run(browser, li_at='supplied')

    assert outcome.job_ids == JOB_IDS
    assert [metrics.failed for metrics in outcome.metrics] == [1]


def test_a_session_lost_part_way_every_time_is_rebuilt_twice(run: Run) -> None:
    browser = LinkedinBrowser(accepted=('supplied',))

    def lose_session(_job_id: str) -> None:
        del browser.jar['li_at']
        raise WebDriverException('the document is being replaced')

    browser.before_card = lose_session
    outcome = run(browser, li_at='supplied')

    assert outcome.job_ids == []
    assert outcome.error is None
    assert browser.searches == 1 + 2 + 2


def test_a_failure_on_an_error_page_does_not_spend_a_credential(run: Run) -> None:
    browser = LinkedinBrowser(accepted=('supplied',))

    def fail_on_an_error_page(job_id: str) -> None:
        if job_id == JOB_IDS[0]:
            browser.is_error_page = True
            raise WebDriverException('the document is being replaced')

    browser.before_card = fail_on_an_error_page
    outcome = run(browser, li_at='supplied')

    assert len(outcome.errors) == 1
    assert outcome.invalid_sessions == 0
    assert [cookie['name'] for cookie in browser.added] == ['li_at']


def test_a_run_ending_on_an_error_page_still_reports_the_issued_session(run: Run) -> None:
    browser = LinkedinBrowser(remembered=('rm', 'b'), issued=('issued',))

    def fail_on_an_error_page(job_id: str) -> None:
        if job_id == JOB_IDS[1]:
            browser.is_error_page = True
            raise WebDriverException('the document is being replaced')

    browser.before_card = fail_on_an_error_page
    browser.before_search = lambda number: setattr(browser, 'is_error_page', number > 1)
    outcome = run(browser, li_rm='rm', bcookie='b')

    assert outcome.refreshed == ['issued']
