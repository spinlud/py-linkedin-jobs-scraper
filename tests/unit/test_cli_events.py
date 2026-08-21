"""Offline tests for CLI feedback, exit-code, logger and colour logic.

No network, no browser, no credentials. The scraper is never constructed or run.
"""
from __future__ import annotations

import io
import logging

import pytest

from linkedin_jobs_scraper.cli.color import Colorizer, color_enabled
from linkedin_jobs_scraper.cli.events import Feedback
from linkedin_jobs_scraper.cli.main import _configure_logger, compute_exit_code
from linkedin_jobs_scraper.config import Config
from linkedin_jobs_scraper.events import EventBegin, EventMetrics, EventNotFound, EventSession


class FakeStream(io.StringIO):
    """In-memory stream with a controllable tty flag."""

    def __init__(self, is_tty: bool = False) -> None:
        super().__init__()
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


def _feedback(quiet: bool, is_tty: bool = True) -> tuple[Feedback, FakeStream]:
    stream = FakeStream(is_tty=is_tty)
    return Feedback(quiet, stream, Colorizer(False)), stream


def _metrics() -> EventMetrics:
    metrics = EventMetrics()
    metrics.processed = 3
    return metrics


# --- feedback stream routing ---------------------------------------------

def test_feedback_writes_to_injected_stream_not_stdout(capsys) -> None:
    feedback, stream = _feedback(quiet=False)
    feedback.on_begin(EventBegin(job_total=42))
    feedback.on_metrics(_metrics())
    feedback.on_end()

    assert '42' in stream.getvalue()
    assert 'processed=3' in stream.getvalue()
    assert capsys.readouterr().out == ''


def test_quiet_suppresses_informational_events() -> None:
    feedback, stream = _feedback(quiet=True)
    feedback.on_begin(EventBegin(job_total=42))
    feedback.on_metrics(_metrics())
    feedback.on_session_refreshed(EventSession(li_at='cookie'))
    feedback.on_end()

    assert stream.getvalue() == ''


def test_quiet_still_emits_and_records_error_states() -> None:
    feedback, stream = _feedback(quiet=True)
    feedback.on_error('boom')
    feedback.on_not_found(EventNotFound(job_id='999'))
    feedback.on_invalid_session()

    output = stream.getvalue()
    assert 'boom' in output
    assert '999' in output
    assert 'session invalid' in output
    assert feedback.not_found is True
    assert feedback.invalid_session is True


# --- exit-code precedence -------------------------------------------------

def test_exit_code_precedence() -> None:
    assert compute_exit_code(False, True, False, False) == 2   # INVALID_SESSION
    assert compute_exit_code(True, False, False, False) == 2   # InvalidCookieException
    assert compute_exit_code(False, False, True, False) == 3   # NOT_FOUND
    assert compute_exit_code(False, False, False, True) == 1   # generic Exception
    assert compute_exit_code(False, False, False, False) == 0  # clean
    assert compute_exit_code(False, True, True, False) == 2    # INVALID_SESSION beats NOT_FOUND


# --- logger configuration -------------------------------------------------

def test_verbose_maps_to_levels_when_log_level_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('LOG_LEVEL', raising=False)
    logger = logging.getLogger(Config.LOGGER_NAMESPACE)

    _configure_logger(0)
    assert logger.level == logging.WARNING
    _configure_logger(1)
    assert logger.level == logging.INFO
    _configure_logger(2)
    assert logger.level == logging.DEBUG


def test_explicit_log_level_is_not_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('LOG_LEVEL', 'ERROR')
    logger = logging.getLogger(Config.LOGGER_NAMESPACE)
    logger.setLevel(logging.CRITICAL)

    _configure_logger(2)
    assert logger.level == logging.CRITICAL


# --- colour gating --------------------------------------------------------

def test_color_disabled_by_no_color_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('NO_COLOR', raising=False)
    assert color_enabled(True, FakeStream(is_tty=True)) is False


def test_color_disabled_by_no_color_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('NO_COLOR', '1')
    assert color_enabled(False, FakeStream(is_tty=True)) is False


def test_color_disabled_when_not_a_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('NO_COLOR', raising=False)
    assert color_enabled(False, FakeStream(is_tty=False)) is False


def test_color_enabled_when_all_allow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('NO_COLOR', raising=False)
    assert color_enabled(False, FakeStream(is_tty=True)) is True
