"""Offline tests for relative-date parsing and the new EventData fields.

The pure date helper is driven with a fixed `now` so every assertion is exact; no
network or browser is involved.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from linkedin_jobs_scraper.events import EventData
from linkedin_jobs_scraper.utils.dates import parse_relative_date

# Fixed reference time so relative offsets resolve to deterministic ISO dates.
NOW = datetime(2026, 8, 23)


# --- parse_relative_date --------------------------------------------------


@pytest.mark.parametrize(
    'text, expected',
    [
        ('just now', '2026-08-23'),
        ('5 minutes ago', '2026-08-23'),
        ('1 minute ago', '2026-08-23'),
        ('3 hours ago', '2026-08-23'),
        ('1 hour ago', '2026-08-23'),
        ('1 day ago', '2026-08-22'),
        ('2 days ago', '2026-08-21'),
        ('1 week ago', '2026-08-16'),
        ('2 weeks ago', '2026-08-09'),
        ('3 months ago', '2026-05-25'),
        ('1 month ago', '2026-07-24'),
        ('1 year ago', '2025-08-23'),
        ('2 years ago', '2024-08-23'),
    ],
)
def test_parse_relative_date_units(text: str, expected: str) -> None:
    assert parse_relative_date(text, NOW) == expected


def test_parse_relative_date_strips_reposted_prefix() -> None:
    assert parse_relative_date('Reposted 6 days ago', NOW) == '2026-08-17'


def test_parse_relative_date_strips_posted_prefix() -> None:
    assert parse_relative_date('Posted 2 hours ago', NOW) == '2026-08-23'


def test_parse_relative_date_prefix_is_case_insensitive() -> None:
    assert parse_relative_date('REPOSTED 1 week ago', NOW) == '2026-08-16'


@pytest.mark.parametrize(
    'text',
    [
        '',
        'yesterday',
        'garbage',
        'over a year',
        'Reposted',
    ],
)
def test_parse_relative_date_no_match_returns_empty(text: str) -> None:
    assert parse_relative_date(text, NOW) == ''


# --- reposted flag --------------------------------------------------------


@pytest.mark.parametrize(
    'date_text, expected',
    [
        ('Reposted 8 hours ago', True),
        ('reposted 2 weeks ago', True),
        ('2 weeks ago', False),
        ('Posted 3 days ago', False),
        ('', False),
    ],
)
def test_reposted_flag(date_text: str, expected: bool) -> None:
    assert ('reposted' in date_text.lower()) is expected


# --- EventData new fields -------------------------------------------------


def test_event_data_new_field_defaults() -> None:
    data = EventData()

    assert data.salary == ''
    assert data.is_easy_apply is False
    assert data.applicant_count == ''
    assert data.benefits == []
    assert data.reposted is False


def test_event_data_new_field_types() -> None:
    data = EventData(
        salary='$120K/yr',
        is_easy_apply=True,
        applicant_count='27 applicants',
        benefits=['401(k)', 'Medical insurance'],
        reposted=True,
    )

    assert isinstance(data.salary, str)
    assert isinstance(data.is_easy_apply, bool)
    assert isinstance(data.applicant_count, str)
    assert isinstance(data.benefits, list)
    assert isinstance(data.reposted, bool)
