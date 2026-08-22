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
from .mapping import describe_locations
from .output import Writer
from .spinner import Spinner

if TYPE_CHECKING:
    from ..linkedin_scraper import LinkedinScraper
    from .args import CliConfig

# Left-hand label column width for the pre-run summary.
_ANNOUNCE_LABEL_WIDTH = 11


class Feedback:
    """Renders scraper lifecycle events onto a diagnostics stream and records outcomes.

    Informational events (BEGIN, METRICS progress, END summary, SESSION_REFRESHED) obey
    --quiet; ERROR, NOT_FOUND and INVALID_SESSION always print. Per-job METRICS drive the
    animated spinner's label; every standalone line is printed with the spinner cleared.
    """

    def __init__(self, quiet: bool, stream: TextIO, colorizer: Colorizer,
                 spinner: Spinner) -> None:
        self._quiet = quiet
        self._stream = stream
        self._color = colorizer
        self._spinner = spinner
        self._metrics: EventMetrics | None = None
        self._location_labels: list[str] = []
        self._begin_index = 0
        self.invalid_session = False
        self.not_found = False

    def set_location_labels(self, labels: list[str]) -> None:
        """Provide the ordered location labels BEGIN events are indexed against."""
        self._location_labels = list(labels)
        self._begin_index = 0

    @staticmethod
    def _format_metrics(metrics: EventMetrics) -> str:
        return (
            f'processed={metrics.processed} failed={metrics.failed} '
            f'missed={metrics.missed} skipped={metrics.skipped} '
            f'throttled={metrics.throttled} pace={metrics.pace}s')

    def _println(self, text: str) -> None:
        """Print a standalone line with the animated spinner cleared under its lock."""
        with self._spinner.pause():
            self._stream.write(text + '\n')
            self._stream.flush()

    @staticmethod
    def _on_off(value: bool) -> str:
        return 'on' if value else 'off'

    def _row(self, label: str, value: str) -> str:
        """Format one aligned summary row: a dim left label followed by its value."""
        padded = label.ljust(_ANNOUNCE_LABEL_WIDTH)
        return '   ' + self._color.dim(padded) + value

    def _format_locations(self, config: 'CliConfig') -> str:
        return ', '.join(describe_locations(config))

    def _format_filters(self, config: 'CliConfig') -> str:
        segments: list[str] = []
        if config.relevance is not None:
            segments.append(f'relevance={config.relevance}')
        if config.time is not None:
            segments.append(f'time={config.time}')
        if config.salary is not None:
            segments.append(f'salary={config.salary}')
        if config.company_jobs_url is not None:
            segments.append(f'company-jobs-url={config.company_jobs_url}')
        if config.type:
            segments.append(f'type={",".join(config.type)}')
        if config.experience:
            segments.append(f'experience={",".join(config.experience)}')
        if config.workplace:
            segments.append(f'workplace={",".join(config.workplace)}')
        if config.industry:
            segments.append(f'industry={",".join(config.industry)}')
        return ' '.join(segments)

    def _format_options(self, config: 'CliConfig') -> str:
        return (
            f'apply-link={self._on_off(config.apply_link)} '
            f'skip-promoted={self._on_off(config.skip_promoted_jobs)} '
            f'page-offset={config.page_offset}')

    def _format_driver(self, config: 'CliConfig') -> str:
        parts = [
            f'headless={self._on_off(not config.no_headless)}',
            f'slow-mo={config.slow_mo}s',
            f'adaptive={self._on_off(not config.no_adaptive_slow_mo)}',
        ]
        if config.chrome_user_data_dir:
            parts.append(f'profile={config.chrome_user_data_dir}')
        return ' '.join(parts)

    def _title(self, text: str) -> str:
        return '🔍 ' + self._color.cyan(self._color.bold(text))

    def announce(self, config: 'CliConfig') -> None:
        """Print a compact, aligned summary of what is about to run, to the diagnostics stream."""
        if self._quiet:
            return
        if config.subcommand == 'job':
            self._println(self._title(f'job {config.url_or_id}'))
            self._println(self._row('options', f'apply-link={self._on_off(config.apply_link)}'))
            self._println(self._row('driver', self._format_driver(config)))
            return

        self._println(self._title(config.query or '(no keywords)'))
        self._println(self._row('locations', self._format_locations(config)))
        self._println(self._row('limit', str(config.limit)))
        filters = self._format_filters(config)
        if filters:
            self._println(self._row('filters', filters))
        self._println(self._row('options', self._format_options(config)))
        self._println(self._row('driver', self._format_driver(config)))

    def on_begin(self, begin: EventBegin) -> None:
        if self._quiet:
            return
        # Margin before every section but the first; the writer no longer emits it.
        if self._begin_index > 0:
            self._println('')

        location: str | None = None
        if self._begin_index < len(self._location_labels):
            location = self._location_labels[self._begin_index]
        self._begin_index += 1

        count = 'results: unknown total' if begin.job_total < 0 else f'~{begin.job_total} results'
        if location is not None:
            self._println('📍 ' + self._color.cyan(self._color.bold(location)) + '   ' + count)
        else:
            self._println(count)
        self._spinner.set_label('searching…')

    def on_metrics(self, metrics: EventMetrics) -> None:
        self._metrics = metrics
        if self._quiet:
            return
        self._spinner.set_label(self._format_metrics(metrics))

    def on_error(self, message: str) -> None:
        self._println('❌ ' + self._color.red(f'error: {message}'))

    def on_session_refreshed(self, session: EventSession) -> None:
        if self._quiet:
            return
        self._println('session refreshed')

    def on_not_found(self, not_found: EventNotFound) -> None:
        self.not_found = True
        self._println('⚠️ ' + self._color.yellow(f'job not found: {not_found.job_id}'))

    def on_invalid_session(self) -> None:
        self.invalid_session = True
        self._println('❌ ' + self._color.red('error: session invalid or refused'))

    def on_end(self) -> None:
        self._spinner.stop()
        if self._quiet:
            return
        if self._metrics is not None:
            self._println('done: ' + self._format_metrics(self._metrics))
        else:
            self._println('done')
        self._println('')


def create_feedback(config: 'CliConfig', spinner: Spinner) -> Feedback:
    """Build the stderr Feedback, keying colour off stderr being a tty."""
    colorizer = Colorizer(color_enabled(config.no_color, sys.stderr))
    return Feedback(config.quiet, sys.stderr, colorizer, spinner)


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
