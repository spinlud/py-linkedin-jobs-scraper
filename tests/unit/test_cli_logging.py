"""Offline tests for how the CLI surfaces the library's log records on stderr.

main() is driven with _dispatch replaced by a stand-in that logs through the library's
logger helpers, so no browser or credential is involved.
"""

from __future__ import annotations

import importlib
import logging
import subprocess
from collections.abc import Iterator
import sys

import pytest

from linkedin_jobs_scraper.cli.args import CliConfig
from linkedin_jobs_scraper.config import Config
from linkedin_jobs_scraper.utils import logger

main_module = importlib.import_module('linkedin_jobs_scraper.cli.main')


def _log_every_level(
    _config: CliConfig, _writer: object, _feedback: object, _spinner: object
) -> None:
    logger.debug('a debug record')
    logger.info('an info record')
    logger.warn('a warning record')


def _stderr_of(
    argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> str:
    monkeypatch.setattr(main_module, '_dispatch', _log_every_level)
    main_module.main([*argv, 'jobs', 'engineer', '--limit', '1', '--no-color'])
    return capsys.readouterr().err


@pytest.fixture(autouse=True)
def _restore_logger() -> Iterator[None]:
    library_logger = logging.getLogger(Config.LOGGER_NAMESPACE)
    level, handlers = library_logger.level, list(library_logger.handlers)
    yield
    library_logger.setLevel(level)
    library_logger.handlers[:] = handlers


def test_no_flag_shows_only_warnings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv('LOG_LEVEL', raising=False)
    err = _stderr_of([], monkeypatch, capsys)
    assert 'a warning record' in err
    assert 'an info record' not in err
    assert 'a debug record' not in err


def test_single_v_shows_info(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv('LOG_LEVEL', raising=False)
    err = _stderr_of(['-v'], monkeypatch, capsys)
    assert 'an info record' in err
    assert 'a debug record' not in err


def test_double_v_shows_debug(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv('LOG_LEVEL', raising=False)
    err = _stderr_of(['-vv'], monkeypatch, capsys)
    assert 'a debug record' in err
    assert 'an info record' in err


def test_each_record_is_printed_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv('LOG_LEVEL', raising=False)
    _stderr_of(['-v'], monkeypatch, capsys)
    err = _stderr_of(['-v'], monkeypatch, capsys)
    assert err.count('an info record') == 1


@pytest.mark.parametrize('flags', [[], ['-v']])
def test_log_level_debug_wins_over_flags(
    flags: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv('LOG_LEVEL', 'DEBUG')
    err = _stderr_of(flags, monkeypatch, capsys)
    assert 'a debug record' in err


def test_log_level_error_wins_over_flags(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv('LOG_LEVEL', 'ERROR')
    err = _stderr_of(['-vv'], monkeypatch, capsys)
    assert 'an info record' not in err
    assert 'a warning record' not in err


def test_importing_the_library_installs_no_handler() -> None:
    script = (
        'import logging, linkedin_jobs_scraper.linkedin_scraper, linkedin_jobs_scraper.cli.main\n'
        'from linkedin_jobs_scraper.config import Config\n'
        'assert logging.getLogger(Config.LOGGER_NAMESPACE).handlers == []\n'
        'assert logging.getLogger().handlers == []\n'
    )
    subprocess.run([sys.executable, '-c', script], check=True)
