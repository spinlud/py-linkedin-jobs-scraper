"""How LinkedinScraper.run reports a location name the strategy could not resolve."""

from __future__ import annotations

import importlib
import logging

import pytest

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
    def __init__(self, failure: bool) -> None:
        self.failure = failure
        self.runs: list[str] = []

    def resolve_location(self, _driver: object, _tag: str, name: str) -> PickedLocation | None:
        if self.failure:
            raise LocationResolutionError(f'Could not operate the location picker for {name!r}')
        return None

    def run(self, _driver: object, search_url: str, *_args: object) -> None:
        self.runs.append(search_url)


def _run(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, failure: bool) -> tuple[str, FakeStrategy]:
    monkeypatch.setattr(Config, 'LI_AT_COOKIE', 'session-value')
    monkeypatch.setattr(scraper_module, 'build_driver', lambda *_a, **_k: FakeDriver())
    caplog.set_level(logging.WARNING, logger=Config.LOGGER_NAMESPACE)
    scraper = LinkedinScraper()
    strategy = FakeStrategy(failure)
    monkeypatch.setattr(scraper, '_strategy', strategy)
    scraper.run(Query(query='engineer', options=QueryOptions(locations=[LOCATION], limit=1)))
    return caplog.text, strategy


def test_no_match_is_reported_as_no_match(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    text, strategy = _run(monkeypatch, caplog, failure=False)

    assert f"Location {LOCATION!r} matches no LinkedIn location, skip" in text
    assert strategy.runs == []


def test_picker_failure_is_not_reported_as_no_match(
        monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    text, strategy = _run(monkeypatch, caplog, failure=True)

    assert 'matches no LinkedIn location' not in text
    assert f"Could not resolve location {LOCATION!r}" in text
    assert 'Could not operate the location picker' in text
    assert strategy.runs == []
