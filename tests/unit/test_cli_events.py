"""Offline tests for CLI feedback, exit-code, logger and colour logic.

No network, no browser, no credentials. The scraper is never run: main() is driven with
_dispatch replaced.
"""
from __future__ import annotations

import importlib
import io
import logging

import pytest

from linkedin_jobs_scraper.cli.args import CliConfig
from linkedin_jobs_scraper.cli.color import Colorizer, color_enabled
from linkedin_jobs_scraper.cli.events import Feedback
from linkedin_jobs_scraper.cli.main import _configure_logger, compute_exit_code
from linkedin_jobs_scraper.cli.spinner import Spinner
from linkedin_jobs_scraper.config import Config
from linkedin_jobs_scraper.events import EventBegin, EventMetrics, EventNotFound, EventSession
from linkedin_jobs_scraper.exceptions import InvalidCookieException

main_module = importlib.import_module('linkedin_jobs_scraper.cli.main')


class FakeStream(io.StringIO):
    """In-memory stream with a controllable tty flag."""

    def __init__(self, is_tty: bool = False) -> None:
        super().__init__()
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


def _disabled_spinner() -> Spinner:
    return Spinner(io.StringIO(), enabled=False)


def _feedback(quiet: bool, is_tty: bool = True,
              colorizer: Colorizer | None = None) -> tuple[Feedback, FakeStream]:
    stream = FakeStream(is_tty=is_tty)
    color = colorizer if colorizer is not None else Colorizer(False)
    return Feedback(quiet, stream, color, _disabled_spinner()), stream


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


def test_session_refreshed_prints_notice_without_token() -> None:
    feedback, stream = _feedback(quiet=False)
    feedback.on_session_refreshed(EventSession(li_at='secret-token'))

    output = stream.getvalue()
    assert 'session refreshed' in output
    assert 'secret-token' not in output
    assert 'li_at' not in output


def test_quiet_still_emits_and_records_error_states() -> None:
    feedback, stream = _feedback(quiet=True)
    feedback.on_error('boom')
    feedback.on_not_found(EventNotFound(job_id='999'))
    feedback.on_invalid_session()
    feedback.report_invalid_session('No session available: no profile.')

    output = stream.getvalue()
    assert 'boom' in output
    assert '999' in output
    assert '❌ error: No session available: no profile.' in output
    assert feedback.not_found is True
    assert feedback.invalid_session is True


# --- per-section begin opener --------------------------------------------

def test_begin_prints_location_and_count() -> None:
    feedback, stream = _feedback(quiet=False)
    feedback.set_location_labels(['London'])
    feedback.on_begin(EventBegin(job_total=200))

    assert '📍 London   ~200 results' in stream.getvalue()


def test_begin_unknown_total_with_location() -> None:
    feedback, stream = _feedback(quiet=False)
    feedback.set_location_labels(['Berlin'])
    feedback.on_begin(EventBegin(job_total=-1))

    assert '📍 Berlin   results: unknown total' in stream.getvalue()


def test_begin_indexes_labels_in_order_and_blanks_between_sections() -> None:
    feedback, stream = _feedback(quiet=False)
    feedback.set_location_labels(['London', 'Berlin'])
    feedback.on_begin(EventBegin(job_total=10))
    feedback.on_begin(EventBegin(job_total=20))
    lines = stream.getvalue().split('\n')

    assert lines[0] == '📍 London   ~10 results'
    # A single blank line precedes the second section, not the first.
    assert lines[1] == ''
    assert lines[2] == '📍 Berlin   ~20 results'


def test_begin_without_labels_prints_count_only() -> None:
    feedback, stream = _feedback(quiet=False)
    feedback.on_begin(EventBegin(job_total=42))

    output = stream.getvalue()
    assert '📍' not in output
    assert '~42 results' in output


def test_begin_index_overflow_falls_back_to_count() -> None:
    feedback, stream = _feedback(quiet=False)
    feedback.set_location_labels(['London'])
    feedback.on_begin(EventBegin(job_total=10))
    feedback.on_begin(EventBegin(job_total=20))
    lines = [line for line in stream.getvalue().split('\n') if line]

    assert lines[0] == '📍 London   ~10 results'
    # The second BEGIN has no label; it prints the count with no location prefix.
    assert lines[1] == '~20 results'


# --- emoji prefixes and end margin ---------------------------------------

def test_error_lines_carry_emoji_prefixes() -> None:
    feedback, stream = _feedback(quiet=False)
    feedback.on_error('boom')
    feedback.on_not_found(EventNotFound(job_id='999'))
    feedback.report_invalid_session()

    output = stream.getvalue()
    assert '❌ error: boom' in output
    assert '⚠️ job not found: 999' in output
    assert '❌ error: session invalid or refused' in output


def test_invalid_session_event_records_without_printing() -> None:
    feedback, stream = _feedback(quiet=False)
    feedback.on_invalid_session()

    assert feedback.invalid_session is True
    assert stream.getvalue() == ''


@pytest.mark.parametrize('reason', [None, ''])
def test_invalid_session_report_falls_back_to_generic_line(reason: str | None) -> None:
    feedback, stream = _feedback(quiet=False)
    feedback.report_invalid_session(reason)

    assert stream.getvalue() == '❌ error: session invalid or refused\n'


def test_invalid_session_report_carries_reason() -> None:
    feedback, stream = _feedback(quiet=False)
    feedback.report_invalid_session('LinkedIn refused every session available.')

    assert stream.getvalue() == '❌ error: LinkedIn refused every session available.\n'


def test_end_prints_blank_line_after_done() -> None:
    feedback, stream = _feedback(quiet=False)
    feedback.on_metrics(_metrics())
    feedback.on_end()

    lines = stream.getvalue().split('\n')
    # The done line, then a blank line, then the trailing newline split.
    done_index = next(i for i, line in enumerate(lines) if line.startswith('done:'))
    assert lines[done_index + 1] == ''


def test_end_without_metrics_still_has_blank_margin() -> None:
    feedback, stream = _feedback(quiet=False)
    feedback.on_end()

    # With no metrics captured the summary renders a zeroed single line.
    assert stream.getvalue() == (
        'done: processed=0 failed=0 missed=0 skipped=0 throttled=0 pace=0.0s\n\n')


def _metrics_processed(count: int) -> EventMetrics:
    metrics = EventMetrics()
    metrics.processed = count
    return metrics


def test_end_multi_location_summary_breaks_down_and_totals() -> None:
    feedback, stream = _feedback(quiet=False)
    feedback.set_location_labels(['United States', 'Remote'])
    feedback.on_begin(EventBegin(job_total=100))
    feedback.on_metrics(_metrics_processed(10))
    feedback.on_begin(EventBegin(job_total=50))
    feedback.on_metrics(_metrics_processed(10))
    feedback.on_end()

    output = stream.getvalue()
    assert 'United States' in output
    assert 'Remote' in output
    assert 'total' in output
    # The total sums the per-location processed counts.
    assert 'processed=20' in output


# --- pre-run announcement -------------------------------------------------

def _jobs_config(**overrides) -> CliConfig:
    return CliConfig(subcommand='jobs', **overrides)


def test_announce_summarizes_jobs_run() -> None:
    feedback, stream = _feedback(quiet=False)
    config = _jobs_config(
        query='backend engineer',
        location=['London', 'Berlin'],
        limit=3,
        time='past-week',
        experience=['mid-senior'],
    )
    feedback.announce(config)
    output = stream.getvalue()

    assert '🔍 backend engineer' in output
    assert 'London, Berlin' in output
    assert 'limit' in output and '3' in output
    assert 'time=past-week' in output
    assert 'experience=mid-senior' in output
    assert 'headless=on' in output
    assert 'adaptive=on' in output


def test_announce_omits_filters_line_when_none_set() -> None:
    feedback, stream = _feedback(quiet=False)
    feedback.announce(_jobs_config(query='python'))
    output = stream.getvalue()

    assert 'filters' not in output
    # No location given falls back to Worldwide.
    assert 'Worldwide' in output


def test_announce_shows_geo_ids_and_profile() -> None:
    feedback, stream = _feedback(quiet=False)
    config = _jobs_config(query='python', geo_id=['12345'],
                          chrome_user_data_dir='/tmp/profile')
    feedback.announce(config)
    output = stream.getvalue()

    assert 'geoId:12345' in output
    assert 'profile=/tmp/profile' in output


def test_announce_for_single_job_subcommand() -> None:
    feedback, stream = _feedback(quiet=False)
    config = CliConfig(subcommand='job', url_or_id='4012345678', apply_link=True)
    feedback.announce(config)
    output = stream.getvalue()

    assert '🔍 job 4012345678' in output
    assert 'apply-link=on' in output
    assert 'headless=on' in output


def test_announce_is_silent_when_quiet() -> None:
    feedback, stream = _feedback(quiet=True)
    feedback.announce(_jobs_config(query='python'))
    assert stream.getvalue() == ''


def test_announce_without_color_has_no_escapes_but_keeps_emoji() -> None:
    feedback, stream = _feedback(quiet=False, colorizer=Colorizer(False))
    feedback.announce(_jobs_config(query='python'))
    output = stream.getvalue()

    assert '\x1b[' not in output
    assert '🔍' in output


def test_announce_with_color_wraps_query_and_labels() -> None:
    feedback, stream = _feedback(quiet=False, colorizer=Colorizer(True))
    feedback.announce(_jobs_config(query='python'))
    output = stream.getvalue()

    # Emoji is outside the colour envelope; ANSI codes are present when enabled.
    assert '🔍' in output
    assert '\x1b[' in output


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


# --- session failure line from main() --------------------------------------

def _error_lines(text: str) -> list[str]:
    return [line for line in text.split('\n') if 'error' in line]


REFUSAL_MESSAGE = ('LinkedIn refused every session available and would not issue another. '
                   'Check the documentation on how to obtain a valid session cookie.')


@pytest.mark.parametrize('quiet', [False, True])
def test_main_prints_one_line_with_refusal_reason(
        quiet: bool, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def refuse(_config: CliConfig, _writer: object, feedback: Feedback, _spinner: object) -> None:
        feedback.on_invalid_session()
        raise InvalidCookieException(REFUSAL_MESSAGE)

    monkeypatch.setattr(main_module, '_dispatch', refuse)
    argv = ['jobs', 'engineer', '--limit', '1', '--no-color']
    if quiet:
        argv.insert(0, '--quiet')

    exit_code = main_module.main(argv)
    captured = capsys.readouterr()

    assert exit_code == 2
    assert _error_lines(captured.err) == [f'❌ error: {REFUSAL_MESSAGE}']


@pytest.mark.parametrize('error', [None, InvalidCookieException()])
def test_main_falls_back_to_generic_line_without_reason(
        error: InvalidCookieException | None, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    def refuse(_config: CliConfig, _writer: object, feedback: Feedback, _spinner: object) -> None:
        feedback.on_invalid_session()
        if error is not None:
            raise error

    monkeypatch.setattr(main_module, '_dispatch', refuse)

    exit_code = main_module.main(['job', '123456789', '--no-color'])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert _error_lines(captured.err) == ['❌ error: session invalid or refused']
