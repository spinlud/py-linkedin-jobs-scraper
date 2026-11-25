"""The strategy keeps no state of its own: every query thread shares the one instance."""

from __future__ import annotations

import pytest

from linkedin_jobs_scraper import LinkedinScraper
from linkedin_jobs_scraper.config import Config
from linkedin_jobs_scraper.strategies import AuthenticatedStrategy


def test_a_new_attribute_on_the_strategy_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, 'LI_AT_COOKIE', 'session-value')
    strategy = AuthenticatedStrategy(LinkedinScraper())

    with pytest.raises(AttributeError):
        # ruff: ignore[B010] the name is one the type checker would refuse
        setattr(strategy, 'recoveries', 1)
