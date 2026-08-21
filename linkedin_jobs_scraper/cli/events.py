"""Wire scraper events to the CLI output writer and to stderr feedback.

DATA is routed to the output writer (stdout, owned by output.py). Every other event
becomes human feedback on stderr through a Feedback object that also records the
outcomes main() turns into an exit code.
"""
from __future__ import annotations

import sys
from typing import TextIO, TYPE_CHECKING

from ..events import Events, EventBegin, EventMetrics, EventNotFound, EventSession
from .color import Colorizer, color_enabled
from .output import Writer

if TYPE_CHECKING:
    from ..linkedin_scraper import LinkedinScraper
    from .args import CliConfig


class Feedback:
    """Renders scraper lifecycle events onto a diagnostics stream and records outcomes.

    Informational events (BEGIN, METRICS progress, END summary, SESSION_REFRESHED) obey
    --quiet; ERROR, NOT_FOUND and INVALID_SESSION always print. When the stream is a tty
    the per-metrics line updates in place; otherwise only the final END snapshot is shown.
    """

    def __init__(self, quiet: bool, stream: TextIO, colorizer: Colorizer) -> None:
        self._quiet = quiet
        self._stream = stream
        self._color = colorizer
        self._is_tty = stream.isatty()
        self._metrics: EventMetrics | None = None
        self._progress_active = False
        self._last_progress_len = 0
        self.invalid_session = False
        self.not_found = False

    @staticmethod
    def _format_metrics(metrics: EventMetrics) -> str:
        return (
            f'processed={metrics.processed} failed={metrics.failed} '
            f'missed={metrics.missed} skipped={metrics.skipped} '
            f'throttled={metrics.throttled} pace={metrics.pace}s')

    def _write_progress(self, text: str) -> None:
        """Overwrite the current line in place, padding out any shorter previous line."""
        padding = max(self._last_progress_len - len(text), 0)
        self._stream.write('\r' + text + ' ' * padding)
        self._stream.flush()
        self._last_progress_len = len(text)
        self._progress_active = True

    def _end_progress_line(self) -> None:
        if self._progress_active:
            self._stream.write('\n')
            self._stream.flush()
            self._progress_active = False

    def _println(self, text: str) -> None:
        """Finish any in-place progress line, then print a standalone line."""
        self._end_progress_line()
        self._stream.write(text + '\n')
        self._stream.flush()

    def on_begin(self, begin: EventBegin) -> None:
        if self._quiet:
            return
        if begin.job_total < 0:
            self._println('results: unknown total')
        else:
            self._println(f'~{begin.job_total} results')

    def on_metrics(self, metrics: EventMetrics) -> None:
        self._metrics = metrics
        if self._quiet:
            return
        if self._is_tty:
            self._write_progress(self._format_metrics(metrics))

    def on_error(self, message: str) -> None:
        self._println(self._color.red(f'error: {message}'))

    def on_session_refreshed(self, session: EventSession) -> None:
        if self._quiet:
            return
        self._println(
            f'session refreshed; save this li_at for the next run: {session.li_at}')

    def on_not_found(self, not_found: EventNotFound) -> None:
        self.not_found = True
        self._println(self._color.yellow(f'job not found: {not_found.job_id}'))

    def on_invalid_session(self) -> None:
        self.invalid_session = True
        self._println(self._color.red('error: session invalid or refused'))

    def on_end(self) -> None:
        self._end_progress_line()
        if self._quiet:
            return
        if self._metrics is not None:
            self._println('done: ' + self._format_metrics(self._metrics))
        else:
            self._println('done')


def create_feedback(config: 'CliConfig') -> Feedback:
    """Build the stderr Feedback, keying colour off stderr being a tty."""
    colorizer = Colorizer(color_enabled(config.no_color, sys.stderr))
    return Feedback(config.quiet, sys.stderr, colorizer)


def register_events(scraper: 'LinkedinScraper', writer: Writer, feedback: Feedback) -> None:
    """Route DATA to the output writer and every lifecycle event to the feedback object."""
    scraper.on(Events.DATA, lambda data: writer.write(data))
    scraper.on(Events.BEGIN, feedback.on_begin)
    scraper.on(Events.METRICS, feedback.on_metrics)
    scraper.on(Events.ERROR, feedback.on_error)
    scraper.on(Events.SESSION_REFRESHED, feedback.on_session_refreshed)
    scraper.on(Events.NOT_FOUND, feedback.on_not_found)
    scraper.on(Events.INVALID_SESSION, feedback.on_invalid_session)
    scraper.on(Events.END, feedback.on_end)
