"""Which events LinkedinScraper.run emits, and what reaches its caller, when a job fails."""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import ClassVar

import pytest
from selenium.common.exceptions import WebDriverException

from linkedin_jobs_scraper.config import Config
from linkedin_jobs_scraper.events import EventData, Events
from linkedin_jobs_scraper.exceptions import CallbackException
from linkedin_jobs_scraper.linkedin_scraper import LinkedinScraper
from linkedin_jobs_scraper.query import Query, QueryOptions
from linkedin_jobs_scraper.strategies import authenticated_strategy
from linkedin_jobs_scraper.utils.job_record import RawJobDetails, RawJobRecord

scraper_module = importlib.import_module('linkedin_jobs_scraper.linkedin_scraper')

JOB_IDS = ['4438239210', '4492629290']


class FakeDriver:
    """A browser signed in to LinkedIn and showing a results page with JOB_IDS on it."""

    window_handles: ClassVar[list[str]] = ['main']

    def __init__(self, broken_job_id: str | None = None) -> None:
        self.broken_job_id = broken_job_id

    def get(self, _url: str) -> None:
        pass

    def quit(self) -> None:
        pass

    def get_cookie(self, name: str) -> Mapping[str, str | int] | None:
        return {'name': name, 'value': 'session-value'}

    def execute_script(self, script: str, *args: str) -> object:
        if script == authenticated_strategy.GET_JOB_IDS_SCRIPT:
            return JOB_IDS
        if script == authenticated_strategy.READ_JOB_CARD_SCRIPT:
            return self.read_card(args[1])
        if script == authenticated_strategy.READ_JOB_DETAILS_SCRIPT:
            return self.read_details(args[0])
        if 'document.location.hostname' in script:
            return 'www.linkedin.com'
        if "'rendered'" in script:
            return 'rendered'
        if '!!document.querySelector' in script:
            return True
        return None

    def read_card(self, job_id: str) -> RawJobRecord:
        if job_id == self.broken_job_id:
            raise WebDriverException('no such execution context')
        return {
            'job_id': job_id,
            'card_texts': ['Junior Software Engineer', 'Lexroom', 'Milan (Hybrid)'],
            'card_labels': [],
            'card_img': '',
        }

    def read_details(self, job_id: str) -> RawJobDetails:
        return {
            'job_id': job_id,
            'top_texts': [
                'Lexroom',
                'Junior Software Engineer',
                'Milan, Lombardy, Italy · 5 days ago · 94 people clicked apply',
            ],
            'anchors': [],
            'button_labels': [],
            'company_img': '',
            'description_text': 'Lexroom is building the AI platform where legal work gets done.',
            'description_html': '<p>Lexroom is building the AI platform where legal work gets done.</p>',
            'company_texts': ['Lexroom', '201-500 employees'],
        }


def _scraper(monkeypatch: pytest.MonkeyPatch, driver: FakeDriver) -> LinkedinScraper:
    monkeypatch.setattr(Config, 'LI_AT_COOKIE', 'session-value')
    monkeypatch.setattr(scraper_module, 'build_driver', lambda *_a, **_k: driver)
    monkeypatch.setattr(authenticated_strategy, 'sleep', lambda _seconds: None)
    return LinkedinScraper()


def _query(limit: int) -> Query:
    return Query(query='engineer', options=QueryOptions(locations=['103350119'], limit=limit))


def test_an_exception_in_a_data_callback_reaches_the_caller_of_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = _scraper(monkeypatch, FakeDriver())
    delivered: list[str] = []
    errors: list[str] = []

    def failing_callback(data: EventData) -> None:
        delivered.append(data.job_id)
        raise ValueError('bug in the callback')

    scraper.on(Events.DATA, failing_callback)
    scraper.on(Events.ERROR, errors.append)

    with pytest.raises(CallbackException, match='bug in the callback'):
        scraper.run(_query(limit=2))

    assert delivered == JOB_IDS[:1]
    assert errors == []


def test_a_job_the_browser_fails_on_is_an_error_event_and_the_run_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = _scraper(monkeypatch, FakeDriver(broken_job_id=JOB_IDS[0]))
    delivered: list[str] = []
    errors: list[str] = []
    scraper.on(Events.DATA, lambda data: delivered.append(data.job_id))
    scraper.on(Events.ERROR, errors.append)

    scraper.run(_query(limit=1))

    assert delivered == JOB_IDS[1:]
    assert len(errors) == 1
    assert 'no such execution context' in errors[0]


@pytest.mark.parametrize('exception', [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize('event', [Events.BEGIN, Events.DATA, Events.ERROR, Events.METRICS])
def test_a_callback_stops_a_run_by_interrupting_or_exiting(
    monkeypatch: pytest.MonkeyPatch, event: Events, exception: type[BaseException]
) -> None:
    scraper = _scraper(monkeypatch, FakeDriver(broken_job_id=JOB_IDS[0]))
    errors: list[str] = []

    def stopping_callback(_value: object) -> None:
        raise exception

    if event is not Events.ERROR:
        scraper.on(Events.ERROR, errors.append)
    scraper.on(event, stopping_callback)

    with pytest.raises(exception):
        scraper.run(_query(limit=1))

    assert all('no such execution context' in error for error in errors)
