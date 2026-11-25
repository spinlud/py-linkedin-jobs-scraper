"""The shipped example starts, and asks for searches LinkedinScraper accepts."""

from __future__ import annotations

import importlib
import runpy
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from linkedin_jobs_scraper.config import Config
from linkedin_jobs_scraper.strategies import AuthenticatedStrategy
from linkedin_jobs_scraper.utils.location_picker import PickedLocation
from tests.unit.test_location_resolution import FakeDriver

scraper_module = importlib.import_module('linkedin_jobs_scraper.linkedin_scraper')

EXAMPLE = Path(__file__).parents[2] / 'examples' / 'example1.py'


def test_the_example_runs_its_searches(monkeypatch: pytest.MonkeyPatch) -> None:
    searches: list[str] = []
    monkeypatch.setattr(Config, 'LI_AT_COOKIE', 'session-value')
    monkeypatch.setattr(scraper_module, 'build_driver', lambda *_a, **_k: FakeDriver())
    monkeypatch.setattr(
        AuthenticatedStrategy,
        'resolve_location',
        lambda *_a: PickedLocation(geo_id='103644278', label='United States'),
    )
    monkeypatch.setattr(
        AuthenticatedStrategy,
        'run',
        lambda _self, _driver, search_url, *_a: searches.append(search_url),
    )

    runpy.run_path(str(EXAMPLE))

    params = [parse_qs(urlparse(search).query) for search in searches]
    assert [search.get('geoId') for search in params] == [None, ['103644278']]
    assert all(search['keywords'] for search in params)
