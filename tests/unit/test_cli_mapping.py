"""Offline tests for CLI to domain-object mapping (linkedin_jobs_scraper.cli.mapping).

Pure translation: no network, no browser, no credentials.
"""
from __future__ import annotations

from enum import Enum

import pytest

from linkedin_jobs_scraper.cli.args import parse_args
from linkedin_jobs_scraper.cli.mapping import (
    RELEVANCE_CHOICES,
    TIME_CHOICES,
    SALARY_CHOICES,
    TYPE_CHOICES,
    EXPERIENCE_CHOICES,
    WORKPLACE_CHOICES,
    INDUSTRY_CHOICES,
    _member_to_kebab,
    build_locations,
    build_query,
    build_query_filters,
    build_query_options,
    build_scraper_kwargs,
    describe_locations,
)
from linkedin_jobs_scraper.filters import (
    RelevanceFilters,
    TimeFilters,
    TypeFilters,
    ExperienceLevelFilters,
    OnSiteOrRemoteFilters,
    IndustryFilters,
    SalaryBaseFilters,
)
from linkedin_jobs_scraper.query import Location, Query, QueryFilters, QueryOptions


ENUM_CHOICE_CASES = [
    (RelevanceFilters, RELEVANCE_CHOICES, ''),
    (TimeFilters, TIME_CHOICES, ''),
    (TypeFilters, TYPE_CHOICES, ''),
    (ExperienceLevelFilters, EXPERIENCE_CHOICES, ''),
    (OnSiteOrRemoteFilters, WORKPLACE_CHOICES, ''),
    (IndustryFilters, INDUSTRY_CHOICES, ''),
    (SalaryBaseFilters, SALARY_CHOICES, 'SALARY_'),
]


@pytest.mark.parametrize('enum_cls, choices, strip_prefix', ENUM_CHOICE_CASES)
def test_every_member_roundtrips_through_a_kebab_token(
    enum_cls: type[Enum], choices: dict[str, Enum], strip_prefix: str
) -> None:
    # Every member is reachable by exactly one token, and the map has no extras.
    assert set(choices.values()) == set(enum_cls)
    assert len(choices) == len(list(enum_cls))
    for token, member in choices.items():
        assert _member_to_kebab(member.name, strip_prefix) == token
        assert choices[token] is member


def test_salary_special_case() -> None:
    assert SALARY_CHOICES['80k'] is SalaryBaseFilters.SALARY_80K


def test_list_filter_accepts_comma_and_repeated_forms() -> None:
    comma = build_query_filters(parse_args(['jobs', 'x', '--type', 'full-time,contract']))
    repeated = build_query_filters(
        parse_args(['jobs', 'x', '--type', 'full-time', '--type', 'contract']))
    expected = [TypeFilters.FULL_TIME, TypeFilters.CONTRACT]

    assert comma is not None and repeated is not None
    assert comma.type == expected
    assert repeated.type == expected


def test_workplace_lands_in_on_site_or_remote() -> None:
    filters = build_query_filters(parse_args(['jobs', 'x', '--workplace', 'remote']))
    assert filters is not None
    assert filters.on_site_or_remote == [OnSiteOrRemoteFilters.REMOTE]


def test_build_query_filters_returns_none_without_filters() -> None:
    assert build_query_filters(parse_args(['jobs', 'x'])) is None


def test_only_provided_filter_fields_are_set() -> None:
    filters = build_query_filters(parse_args(['jobs', 'x', '--relevance', 'recent']))
    assert filters is not None
    assert filters.relevance is RelevanceFilters.RECENT
    # Scalars the user did not give stay None; list fields normalize to empty lists.
    assert filters.time is None
    assert filters.base_salary is None
    assert filters.company_jobs_url is None
    assert filters.type == []
    assert filters.experience == []
    assert filters.on_site_or_remote == []
    assert filters.industry == []


def test_build_query_and_options_shape() -> None:
    query = build_query(parse_args([
        'jobs', 'python',
        '--location', 'Remote',
        '--limit', '10',
        '--apply-link',
        '--skip-promoted-jobs',
        '--page-offset', '1',
        '--relevance', 'relevant',
    ]))

    assert isinstance(query, Query)
    assert query.query == 'python'
    options = query.options
    assert isinstance(options, QueryOptions)
    assert options.limit == 10
    assert options.locations == ['Remote']
    assert options.apply_link is True
    assert options.skip_promoted_jobs is True
    assert options.page_offset == 1
    assert isinstance(options.filters, QueryFilters)
    assert options.filters.relevance is RelevanceFilters.RELEVANT


def test_build_query_options_without_filters_leaves_filters_none() -> None:
    options = build_query_options(parse_args(['jobs', 'python']))
    assert options.filters is None


def test_geo_id_becomes_location_object_with_id_label() -> None:
    locations = build_locations(parse_args(['jobs', 'x', '--geo-id', '90000070']))
    assert locations is not None
    assert len(locations) == 1
    location = locations[0]
    assert isinstance(location, Location)
    assert location.geo_id == '90000070'
    assert location.label == '90000070'


def test_plain_location_stays_a_string() -> None:
    locations = build_locations(parse_args(['jobs', 'x', '--location', 'New York']))
    assert locations == ['New York']


def test_build_locations_none_when_absent() -> None:
    assert build_locations(parse_args(['jobs', 'x'])) is None


def test_build_scraper_kwargs_defaults() -> None:
    kwargs = build_scraper_kwargs(parse_args(['jobs', 'python']))
    assert kwargs['headless'] is True
    assert kwargs['adaptive_slow_mo'] is True
    assert 'max_workers' not in kwargs
    assert 'chrome_options' not in kwargs


def test_build_scraper_kwargs_flags_and_passthrough() -> None:
    kwargs = build_scraper_kwargs(parse_args([
        'jobs', 'python',
        '--no-headless',
        '--no-adaptive-slow-mo',
        '--slow-mo', '1.5',
        '--page-load-timeout', '30',
        '--chrome-executable-path', '/bin/chromedriver',
        '--chrome-binary-location', '/bin/chrome',
        '--chrome-user-data-dir', '/tmp/profile',
        '--interactive-login',
    ]))

    assert kwargs['headless'] is False
    assert kwargs['adaptive_slow_mo'] is False
    assert kwargs['slow_mo'] == 1.5
    assert kwargs['page_load_timeout'] == 30
    assert kwargs['chrome_executable_path'] == '/bin/chromedriver'
    assert kwargs['chrome_binary_location'] == '/bin/chrome'
    assert kwargs['chrome_user_data_dir'] == '/tmp/profile'
    assert kwargs['interactive_login'] is True
    assert 'max_workers' not in kwargs
    assert 'chrome_options' not in kwargs


# --- describe_locations ---------------------------------------------------

def test_describe_locations_defaults_to_worldwide() -> None:
    assert describe_locations(parse_args(['jobs', 'x'])) == ['Worldwide']


def test_describe_locations_lists_location_names_in_order() -> None:
    labels = describe_locations(
        parse_args(['jobs', 'x', '--location', 'London', '--location', 'Berlin']))
    assert labels == ['London', 'Berlin']


def test_describe_locations_renders_geo_ids() -> None:
    labels = describe_locations(
        parse_args(['jobs', 'x', '--geo-id', '90000070', '--geo-id', '12345']))
    assert labels == ['geoId:90000070', 'geoId:12345']
