"""The ways a page of results, a card or a location can end, as LinkedinScraper.run reports them."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import TypeAlias
from urllib.parse import parse_qs, urlsplit

import pytest

from linkedin_jobs_scraper.config import Config
from linkedin_jobs_scraper.events import EventBegin, EventMetrics, Events
from linkedin_jobs_scraper.linkedin_scraper import LinkedinScraper
from linkedin_jobs_scraper.query import Query, QueryOptions
from linkedin_jobs_scraper.strategies import authenticated_strategy
from linkedin_jobs_scraper.utils.location_picker import (
    READ_CONTROL_LABEL_SCRIPT,
    LocationCache,
    PickedLocation,
)

from .test_job_events import FakeDriver, scraper_module

Event: TypeAlias = tuple[str, object]


class ResultsBrowser(FakeDriver):
    """A signed in browser, and the pages of results LinkedIn has for it, the last one of which is
    served past the end too."""

    def __init__(self, *pages: Sequence[str], labels: Sequence[str] = ()) -> None:
        super().__init__()
        self.pages = pages
        self.labels = iter(labels)
        # The `start` of each page of results opened
        self.opened: list[int] = []
        self.unrendered_openings: set[int] = set()
        self.card_states: dict[str, str] = {}
        self.cards_gone: set[str] = set()
        self.without_details: set[str] = set()
        self.guest_openings: set[int] = set()
        self.jar = {'li_at': 'session-value'}

    def get(self, url: str) -> None:
        if '/jobs/search' in url:
            self.opened.append(int(parse_qs(urlsplit(url).query)['start'][0]))

    def add_cookie(self, cookie: dict[str, str]) -> None:
        self.jar[cookie['name']] = cookie['value']

    def delete_cookie(self, name: str) -> None:
        self.jar.pop(name, None)

    def get_cookie(self, name: str) -> dict[str, str | int] | None:
        return {'name': name, 'value': self.jar[name]} if name in self.jar else None

    @property
    def _job_ids(self) -> Sequence[str]:
        opening = len(self.opened)
        if opening in self.unrendered_openings | self.guest_openings:
            return []
        return self.pages[min(self.opened[-1] // 25, len(self.pages) - 1)]

    def execute_script(self, script: str, *args: str) -> object:
        if script == authenticated_strategy.GET_JOB_IDS_SCRIPT:
            return list(self._job_ids)
        if script == authenticated_strategy.RESULTS_TOTAL_TEXT_SCRIPT:
            return '0 results' if self.pages == ([],) else ''
        if script == READ_CONTROL_LABEL_SCRIPT:
            return f'Location {next(self.labels, "Italy")}'
        if script == authenticated_strategy.READ_JOB_CARD_SCRIPT and args[1] in self.cards_gone:
            return None
        if (
            script == authenticated_strategy.READ_JOB_DETAILS_SCRIPT
            and args[0] in self.without_details
        ):
            return None
        if '!document.querySelector(arguments[0]) &&' in script:
            return len(self.opened) in self.guest_openings
        if '!!document.querySelector' in script:
            return bool(self._job_ids)
        if 'querySelectorAll(arguments[0]).length' in script:
            return len(self._job_ids)
        if "'rendered'" in script:
            return self.card_states.get(args[0].split('-ref-')[1].rstrip('"]'), 'rendered')
        return super().execute_script(script, *args)


def _search(
    monkeypatch: pytest.MonkeyPatch, browser: ResultsBrowser, limit: int, location: str = '1'
) -> list[Event]:
    """The events of a search, in order: the id of each job, and the counts of the metrics as
    (processed, failed, missed)."""
    monkeypatch.setattr(Config, 'LI_AT_COOKIE', 'session-value')
    monkeypatch.setattr(scraper_module, 'build_driver', lambda *_a, **_k: browser)
    monkeypatch.setattr(authenticated_strategy, 'sleep', lambda _seconds: None)
    events: list[Event] = []

    def on_begin(begin: EventBegin) -> None:
        events.append(('begin', begin.resolved_location))

    def on_metrics(metrics: EventMetrics) -> None:
        events.append(('metrics', (metrics.processed, metrics.failed, metrics.missed)))

    scraper = LinkedinScraper()
    scraper.on(Events.BEGIN, on_begin)
    scraper.on(Events.DATA, lambda data: events.append(('data', data.job_id)))
    scraper.on(Events.ERROR, lambda error: events.append(('error', error)))
    scraper.on(Events.METRICS, on_metrics)
    scraper.on(Events.INVALID_SESSION, lambda: events.append(('invalid session', None)))
    scraper.on(Events.END, lambda: events.append(('end', None)))
    options = QueryOptions(locations=[location], limit=limit)
    scraper.run(Query(query='engineer', options=options))
    return events


def _data(events: list[Event]) -> list[object]:
    return [value for name, value in events if name == 'data']


def test_a_card_that_left_the_list_is_not_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    browser = ResultsBrowser(['1', '2', '3'])
    browser.card_states['1'] = 'missing'
    browser.cards_gone.add('2')

    assert _search(monkeypatch, browser, limit=1) == [
        ('begin', 'Italy'),
        ('data', '3'),
        ('metrics', (1, 0, 0)),
        ('end', None),
    ]


def test_a_card_or_details_that_never_render_are_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    browser = ResultsBrowser(['1', '2', '3'])
    browser.card_states['1'] = 'pending'
    browser.without_details.add('2')

    assert _search(monkeypatch, browser, limit=1) == [
        ('begin', 'Italy'),
        ('data', '3'),
        ('metrics', (1, 2, 0)),
        ('end', None),
    ]


def test_a_search_goes_on_to_the_next_page_until_its_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    browser = ResultsBrowser(['1', '2'], ['2', '3', '4'])

    assert _search(monkeypatch, browser, limit=3) == [
        ('begin', 'Italy'),
        ('data', '1'),
        ('data', '2'),
        ('metrics', (2, 0, 0)),
        # A job the first page delivered is not delivered again
        ('data', '3'),
        ('metrics', (3, 0, 0)),
        ('end', None),
    ]
    assert browser.opened == [0, 25]


def test_an_unlimited_search_ends_when_a_page_has_no_new_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser = ResultsBrowser(['1', '2'], ['3'])

    assert _search(monkeypatch, browser, limit=0) == [
        ('begin', 'Italy'),
        ('data', '1'),
        ('data', '2'),
        ('metrics', (2, 0, 0)),
        ('data', '3'),
        ('metrics', (3, 0, 0)),
        ('end', None),
    ]
    assert browser.opened == [0, 25, 50]


def test_an_unlimited_search_asks_for_no_page_past_a_thousand_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser = ResultsBrowser(*([str(page)] for page in range(50)))

    assert len(_data(_search(monkeypatch, browser, limit=0))) == 40
    assert browser.opened == list(range(0, 1000, 25))


def test_a_search_that_matches_nothing_begins_and_ends(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _search(monkeypatch, ResultsBrowser([]), limit=1) == [('begin', 'Italy'), ('end', None)]


def test_a_page_that_never_renders_begins_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    browser = ResultsBrowser(['1'])
    browser.unrendered_openings.add(1)

    assert _search(monkeypatch, browser, limit=1) == [('end', None)]
    assert browser.opened == [0]


def test_a_next_page_that_does_not_render_is_opened_once_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser = ResultsBrowser(['1'], ['2'])
    browser.unrendered_openings.add(2)

    assert _data(_search(monkeypatch, browser, limit=2)) == ['1', '2']
    assert browser.opened == [0, 25, 25]


def test_a_next_page_that_does_not_render_twice_ends_the_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser = ResultsBrowser(['1'], ['2'])
    browser.unrendered_openings |= {2, 3}

    assert _search(monkeypatch, browser, limit=2) == [
        ('begin', 'Italy'),
        ('data', '1'),
        ('metrics', (1, 0, 0)),
        ('end', None),
    ]
    assert browser.opened == [0, 25, 25]


def test_a_session_refused_on_the_next_page_is_rebuilt_there(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser = ResultsBrowser(['1'], ['2'])
    browser.guest_openings |= {2, 3, 4}

    assert _search(monkeypatch, browser, limit=2) == [
        ('begin', 'Italy'),
        ('data', '1'),
        ('metrics', (1, 0, 0)),
        ('data', '2'),
        ('metrics', (2, 0, 0)),
        ('end', None),
    ]
    # Refused twice, and once more on the way to signing in again
    assert Counter(browser.opened) == {0: 1, 25: 4}


def test_a_session_refused_on_every_next_page_is_rebuilt_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser = ResultsBrowser(['1'], ['2'], ['3'], ['4'])
    for number in (0, 1, 2):
        # A page refused twice, then served
        browser.guest_openings |= {2 + 3 * number, 3 + 3 * number}

    events = _search(monkeypatch, browser, limit=4)

    assert _data(events) == ['1', '2', '3']
    assert browser.opened == [0, 25, 25, 25, 50, 50, 50, 75, 75]
    assert events[-1] == ('end', None)


@pytest.fixture
def _milan(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = LocationCache()
    cache.put('Milan', PickedLocation(geo_id='103350119', label='Milan, Lombardy, Italy'))
    monkeypatch.setattr(authenticated_strategy, 'LOCATION_CACHE', cache)


@pytest.mark.usefixtures('_milan')
def test_a_search_under_another_location_is_opened_once_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser = ResultsBrowser(['1'], labels=['Rome', 'Milan'])

    assert _search(monkeypatch, browser, limit=1, location='Milan') == [
        ('begin', 'Milan'),
        ('data', '1'),
        ('metrics', (1, 0, 0)),
        ('end', None),
    ]
    assert browser.opened == [0, 0]


@pytest.mark.usefixtures('_milan')
def test_a_search_under_another_location_twice_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    browser = ResultsBrowser(['1'], labels=['Rome', 'Rome'])

    assert _search(monkeypatch, browser, limit=1, location='Milan') == [('end', None)]
    assert browser.opened == [0, 0]
