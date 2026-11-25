"""How LinkedinScraper.run reports a location name the strategy could not resolve."""

from __future__ import annotations

import importlib
import logging

import pytest
from urllib.parse import parse_qs, urlparse

from linkedin_jobs_scraper.config import Config
from linkedin_jobs_scraper.exceptions import LocationResolutionError
from linkedin_jobs_scraper.linkedin_scraper import LinkedinScraper
from linkedin_jobs_scraper.query import Query, QueryOptions
from linkedin_jobs_scraper.utils.location_picker import PickedLocation

scraper_module = importlib.import_module('linkedin_jobs_scraper.linkedin_scraper')

LOCATION = 'Nowhere Town'


class FakeDriver:
    def quit(self) -> None:
        pass

    def get_cookie(self, _name: str) -> None:
        return None


class FakeStrategy:
    def __init__(self, failure: bool, picked: PickedLocation | None = None) -> None:
        self.failure = failure
        self.picked = picked
        self.resolved: list[str] = []
        self.runs: list[str] = []
        self.expected_locations: list[str] = []

    def resolve_location(self, _driver: object, _tag: str, name: str) -> PickedLocation | None:
        self.resolved.append(name)
        if self.failure:
            raise LocationResolutionError(f'Could not operate the location picker for {name!r}')
        return self.picked

    def run(
        self,
        _driver: object,
        search_url: str,
        _query: object,
        _location: str,
        _page_offset: int,
        expected_location: str = '',
    ) -> None:
        self.runs.append(search_url)
        self.expected_locations.append(expected_location)


def _scraper(monkeypatch: pytest.MonkeyPatch, strategy: FakeStrategy) -> LinkedinScraper:
    monkeypatch.setattr(Config, 'LI_AT_COOKIE', 'session-value')
    monkeypatch.setattr(scraper_module, 'build_driver', lambda *_a, **_k: FakeDriver())
    scraper = LinkedinScraper()
    monkeypatch.setattr(scraper, '_strategy', strategy)
    return scraper


def _run(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: bool,
    location: str | None = LOCATION,
    picked: PickedLocation | None = None,
) -> tuple[str, FakeStrategy]:
    caplog.set_level(logging.WARNING, logger=Config.LOGGER_NAMESPACE)
    strategy = FakeStrategy(failure, picked)
    scraper = _scraper(monkeypatch, strategy)
    if location is None:
        scraper.run(Query(query='engineer'))
    else:
        scraper.run(Query(query='engineer', options=QueryOptions(locations=[location], limit=1)))
    return caplog.text, strategy


def test_no_match_is_reported_as_no_match(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    text, strategy = _run(monkeypatch, caplog, failure=False)

    assert f'Location {LOCATION!r} matches no LinkedIn location, skip' in text
    assert strategy.runs == []


def test_picker_failure_is_not_reported_as_no_match(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    text, strategy = _run(monkeypatch, caplog, failure=True)

    assert 'matches no LinkedIn location' not in text
    assert f'Could not resolve location {LOCATION!r}' in text
    assert 'Could not operate the location picker' in text
    assert strategy.runs == []


@pytest.mark.parametrize('location', ['Remote', 'remote', ' REMOTE '])
def test_remote_as_a_location_points_at_the_workplace_filter(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, location: str
) -> None:
    text, strategy = _run(monkeypatch, caplog, failure=False, location=location)

    assert f'Location {location!r} matches no LinkedIn location' in text
    assert 'OnSiteOrRemoteFilters.REMOTE' in text
    assert '--workplace remote' in text
    assert strategy.runs == []


def test_other_names_get_no_workplace_hint(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    text, _ = _run(monkeypatch, caplog, failure=False)

    assert '--workplace' not in text


@pytest.mark.parametrize('location', ['Worldwide', ' worldwide '])
def test_worldwide_is_skipped_without_the_picker(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, location: str
) -> None:
    text, strategy = _run(monkeypatch, caplog, failure=False, location=location)

    assert 'no longer offers a worldwide search' in text
    assert "account's current location" in text
    assert strategy.resolved == []
    assert strategy.runs == []


def test_no_location_searches_the_account_location(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _, strategy = _run(monkeypatch, caplog, failure=False, location=None)

    assert len(strategy.runs) == 1
    assert 'geoId' not in parse_qs(urlparse(strategy.runs[0]).query)
    assert strategy.expected_locations == ['']


def test_options_without_locations_search_the_account_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy = FakeStrategy(failure=False)

    _scraper(monkeypatch, strategy).run(Query(query='engineer'), QueryOptions(limit=5))

    assert len(strategy.runs) == 1
    assert 'geoId' not in parse_qs(urlparse(strategy.runs[0]).query)
    assert strategy.expected_locations == ['']


def test_options_locations_reach_a_query_without_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    strategy = FakeStrategy(failure=False)

    _scraper(monkeypatch, strategy).run(
        Query(query='engineer'), QueryOptions(locations=['103350119'])
    )

    assert [parse_qs(urlparse(url).query)['geoId'] for url in strategy.runs] == [['103350119']]


def test_a_picked_location_is_expected_on_the_results_page(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    picked = PickedLocation(geo_id='90000084', label='San Francisco Bay Area')
    _, strategy = _run(monkeypatch, caplog, failure=False, location='San Franci', picked=picked)

    assert parse_qs(urlparse(strategy.runs[0]).query)['geoId'] == ['90000084']
    assert strategy.expected_locations == ['San Francisco Bay Area']


def test_a_geo_id_sets_no_expectation(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _, strategy = _run(monkeypatch, caplog, failure=False, location='103350119')

    assert strategy.expected_locations == ['']
