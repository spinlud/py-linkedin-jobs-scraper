"""How fast a run asks LinkedIn for pages, and what moves that pace."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from linkedin_jobs_scraper.events import EventMetrics, Events
from linkedin_jobs_scraper.linkedin_scraper import LinkedinScraper
from linkedin_jobs_scraper.query import Query, QueryOptions
from linkedin_jobs_scraper.strategies import authenticated_strategy
from linkedin_jobs_scraper.utils.pacing import Pacer

from .test_job_events import FakeDriver, scraper_module


def _refuse(pacer: Pacer, times: int) -> None:
    for _ in range(times):
        pacer.throttled()


def _clean(pacer: Pacer, times: int) -> None:
    for _ in range(times):
        pacer.clean()


def test_the_pace_starts_at_the_floor_and_clean_work_never_takes_it_lower() -> None:
    pacer = Pacer(floor=0.8, ceiling=8)
    assert pacer.delay == 0.8

    _clean(pacer, 100)
    assert pacer.delay == 0.8


def test_each_refusal_doubles_the_pace_up_to_the_ceiling() -> None:
    pacer = Pacer(floor=1, ceiling=5)

    assert [pacer.throttled() for _ in range(4)] == [2, 4, 5, 5]
    assert pacer.delay == 5
    assert pacer.throttled_count == 4


def test_the_pace_eases_once_per_twenty_clean_jobs() -> None:
    pacer = Pacer(floor=1, ceiling=100)
    _refuse(pacer, 3)

    _clean(pacer, 19)
    assert pacer.delay == 8
    assert pacer.clean() == pytest.approx(8 / 1.5)

    _clean(pacer, 19)
    assert pacer.delay == pytest.approx(8 / 1.5)
    assert pacer.clean() == pytest.approx(8 / 2.25)


def test_easing_stops_at_the_floor() -> None:
    pacer = Pacer(floor=1.5, ceiling=2)
    pacer.throttled()

    _clean(pacer, 20)
    assert pacer.delay == 1.5


def test_a_refusal_starts_the_count_of_clean_jobs_over() -> None:
    pacer = Pacer(floor=1, ceiling=100)
    pacer.throttled()
    _clean(pacer, 19)
    pacer.throttled()

    _clean(pacer, 19)
    assert pacer.delay == 4
    pacer.clean()
    assert pacer.delay == pytest.approx(4 / 1.5)


def test_a_ceiling_below_the_floor_is_rejected() -> None:
    with pytest.raises(ValueError, match='ceiling below its floor'):
        Pacer(floor=2, ceiling=1)


class PacedBrowser(FakeDriver):
    """Shows one job per reading: the document on screen after that job, and its refused requests.

    The first `refused_searches` times a page of results is opened, LinkedIn answers with a 429.
    """

    def __init__(
        self, readings: Sequence[tuple[float, int] | None], refused_searches: int = 0
    ) -> None:
        super().__init__()
        self.readings = iter(readings)
        self.job_ids = [str(4438239210 + index) for index in range(len(readings))]
        self.refused_searches = refused_searches
        self.searches = 0

    def get(self, url: str) -> None:
        self.searches += '/jobs/search' in url

    def execute_script(self, script: str, *args: str) -> object:
        if 'performance.timeOrigin' in script:
            return next(self.readings)
        if script == authenticated_strategy.GET_JOB_IDS_SCRIPT:
            return self.job_ids
        if 0 < self.searches <= self.refused_searches:
            return 429 if 'responseStatus' in script else None
        return super().execute_script(script, *args)


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """The sleeps of the runs, none of which is slept."""
    slept: list[float] = []
    monkeypatch.setattr(authenticated_strategy, 'sleep', slept.append)
    monkeypatch.setattr(scraper_module.Config, 'LI_AT_COOKIE', 'session-value')
    return slept


def _run(monkeypatch: pytest.MonkeyPatch, driver: PacedBrowser) -> list[EventMetrics]:
    monkeypatch.setattr(scraper_module, 'build_driver', lambda *_a, **_k: driver)
    scraper = LinkedinScraper()
    reported: list[EventMetrics] = []
    scraper.on(Events.METRICS, reported.append)
    options = QueryOptions(locations=['103350119'], limit=len(driver.job_ids))
    scraper.run(Query(query='engineer', options=options))
    return reported


@pytest.mark.parametrize('slow_mo, slowest', [(0.2, 2.0), (0.8, 8.0), (3, 10), (10, 10)])
def test_slow_mo_is_the_floor_and_ten_times_it_the_ceiling_up_to_ten_seconds(
    sleeps: list[float], slow_mo: float, slowest: float
) -> None:
    pacer = LinkedinScraper(slow_mo=slow_mo).pacer
    assert pacer.delay == slow_mo

    _refuse(pacer, 10)
    assert pacer.delay == slowest


def test_the_default_pace_is_eight_tenths_of_a_second(sleeps: list[float]) -> None:
    assert LinkedinScraper().pacer.delay == 0.8


def test_a_slow_mo_below_the_minimum_is_rejected(sleeps: list[float]) -> None:
    with pytest.raises(ValueError, match='slow_mo'):
        LinkedinScraper(slow_mo=0.19)


def test_a_scraper_that_opted_out_counts_refusals_without_slowing_down(
    sleeps: list[float],
) -> None:
    pacer = LinkedinScraper(adaptive_slow_mo=False).pacer
    _refuse(pacer, 3)

    assert pacer.delay == 0.8
    assert pacer.throttled_count == 3


def test_a_refused_job_fetch_doubles_the_pace_of_the_run(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    (metrics,) = _run(monkeypatch, PacedBrowser([(1, 0), (1, 1), (1, 1)]))

    assert (metrics.processed, metrics.throttled, metrics.pace) == (3, 1, 1.6)
    # The job after the refused one pauses before its card and before its details
    assert sleeps.count(1.6) == 2


def test_a_refusal_after_an_unreadable_reading_is_counted_against_the_reading_before_it(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    (metrics,) = _run(monkeypatch, PacedBrowser([(1, 0), None, (1, 1)]))

    assert (metrics.processed, metrics.throttled, metrics.pace) == (3, 1, 1.6)


@pytest.mark.parametrize('clean_jobs, pace', [(19, 1.6), (20, 1.07)])
def test_twenty_jobs_nobody_refused_ease_the_pace_of_the_run(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], clean_jobs: int, pace: float
) -> None:
    (metrics,) = _run(monkeypatch, PacedBrowser([(1, 0), (1, 1)] + [(1, 1)] * clean_jobs))

    assert (metrics.throttled, metrics.pace) == (1, pace)


@pytest.mark.parametrize(
    'readings',
    [
        pytest.param([(1, 0), (2, 5), (2, 5)], id='another document'),
        pytest.param([(1, 5), (1, 2), (1, 2)], id='a cleared buffer'),
        pytest.param([(1, 0), None, (1, 0)], id='an unreadable buffer'),
    ],
)
def test_a_reading_that_cannot_be_compared_moves_nothing(
    monkeypatch: pytest.MonkeyPatch,
    sleeps: list[float],
    readings: Sequence[tuple[float, int] | None],
) -> None:
    (metrics,) = _run(monkeypatch, PacedBrowser(readings))

    assert (metrics.processed, metrics.throttled, metrics.pace) == (3, 0, 0.8)


@pytest.mark.parametrize(
    'reading',
    [
        pytest.param((2, 1), id='another document'),
        pytest.param((1, 0), id='a cleared buffer'),
        pytest.param(None, id='an unreadable buffer'),
    ],
)
def test_a_reading_that_cannot_be_compared_is_not_clean_work(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], reading: tuple[float, int] | None
) -> None:
    after = reading or (1, 1)
    readings = [(1, 0), (1, 1), *[(1, 1)] * 10, reading, *[after] * 9]
    (metrics,) = _run(monkeypatch, PacedBrowser(readings))

    assert (metrics.throttled, metrics.pace) == (1, 1.6)


def test_a_refused_page_is_asked_for_again_after_a_wait_and_slows_the_run(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    driver = PacedBrowser([(1, 0)], refused_searches=2)
    (metrics,) = _run(monkeypatch, driver)

    assert (metrics.processed, metrics.throttled, metrics.pace) == (1, 2, 3.2)
    assert driver.searches == 3
    # 5 and 15 seconds, give or take half
    assert any(2.5 <= seconds <= 7.5 and seconds != 3.2 for seconds in sleeps)
    assert any(7.5 <= seconds <= 22.5 for seconds in sleeps)


def test_a_page_refused_every_time_is_given_up_after_three_waits(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    driver = PacedBrowser([(1, 0)], refused_searches=100)

    assert _run(monkeypatch, driver) == []
    assert driver.searches == 4
