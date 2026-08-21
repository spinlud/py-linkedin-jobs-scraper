"""Offline tests for CLI argument parsing (linkedin_jobs_scraper.cli.args).

Pure argparse logic: no network, no browser, no credentials.
"""
from __future__ import annotations

import pytest

from linkedin_jobs_scraper.cli.args import CliConfig, parse_args


def test_full_search_line_produces_expected_config() -> None:
    config = parse_args([
        'search', 'python developer',
        '--location', 'Remote',
        '--limit', '50',
        '--apply-link',
        '--skip-promoted-jobs',
        '--page-offset', '2',
        '--relevance', 'recent',
        '--time', 'week',
        '--type', 'full-time',
        '--experience', 'mid-senior',
        '--workplace', 'remote',
    ])

    assert isinstance(config, CliConfig)
    assert config.subcommand == 'search'
    assert config.query == 'python developer'
    assert config.location == ['Remote']
    assert config.geo_id == []
    assert config.limit == 50
    assert config.apply_link is True
    assert config.skip_promoted_jobs is True
    assert config.page_offset == 2
    assert config.relevance == 'recent'
    assert config.time == 'week'
    assert config.type == ['full-time']
    assert config.experience == ['mid-senior']
    assert config.workplace == ['remote']


def test_location_and_geo_id_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit) as exc_info:
        parse_args(['search', 'python', '--location', 'X', '--geo-id', '123'])
    assert exc_info.value.code == 2


def test_invalid_filter_choice_exits() -> None:
    with pytest.raises(SystemExit) as exc_info:
        parse_args(['search', 'python', '--type', 'bogus'])
    assert exc_info.value.code == 2


def test_verbose_count() -> None:
    assert parse_args(['search', 'python']).verbose == 0
    assert parse_args(['-v', 'search', 'python']).verbose == 1
    assert parse_args(['-vv', 'search', 'python']).verbose == 2


def test_scrape_job_requires_positional_id() -> None:
    with pytest.raises(SystemExit) as exc_info:
        parse_args(['scrape-job'])
    assert exc_info.value.code == 2

    config = parse_args(['scrape-job', '4055815184'])
    assert config.subcommand == 'scrape-job'
    assert config.url_or_id == '4055815184'


def test_login_requires_chrome_user_data_dir() -> None:
    with pytest.raises(SystemExit) as exc_info:
        parse_args(['login'])
    assert exc_info.value.code == 2

    config = parse_args(['login', '--chrome-user-data-dir', '/tmp/profile'])
    assert config.subcommand == 'login'
    assert config.chrome_user_data_dir == '/tmp/profile'
