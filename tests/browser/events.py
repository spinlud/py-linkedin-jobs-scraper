from __future__ import annotations

from collections.abc import Callable
from typing import TypeAlias

from linkedin_jobs_scraper import LinkedinScraper
from linkedin_jobs_scraper.events import EventMetrics, Events

RecordedEvent: TypeAlias = tuple[Events, object]


def record_events(scraper: LinkedinScraper) -> list[RecordedEvent]:
    """Every event of the scraper, in order, with what it carries; metrics as a dictionary."""
    recorded: list[RecordedEvent] = []

    def without_value(event: Events) -> Callable[[], None]:
        return lambda: recorded.append((event, None))

    def with_value(event: Events) -> Callable[[object], None]:
        return lambda value: recorded.append(
            (event, vars(value) if isinstance(value, EventMetrics) else value)
        )

    for event in Events:
        is_bare = event in (Events.END, Events.INVALID_SESSION)
        scraper.on(event, without_value(event) if is_bare else with_value(event))
    return recorded
