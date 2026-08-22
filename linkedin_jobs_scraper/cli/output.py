"""Output writers for scraped job data.

The CLI drives a writer through a small lifecycle: begin() opens the destination,
write(event_data) is called once per DATA event as it streams in, and end() closes
the destination. One writer exists per output format behind a common interface, and
create_writer() resolves the format and field selection from the parsed CliConfig.
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, TextIO, TYPE_CHECKING
from urllib.parse import urlsplit

from ..events import EventData
from .color import (
    ANSI_BLUE,
    ANSI_BOLD,
    ANSI_BRIGHT_BLUE,
    ANSI_BRIGHT_GREEN,
    ANSI_BRIGHT_MAGENTA,
    ANSI_BRIGHT_RED,
    ANSI_BRIGHT_YELLOW,
    ANSI_GREEN,
    ANSI_MAGENTA,
    ANSI_RED,
    ANSI_RESET,
    ANSI_YELLOW,
)

from .spinner import Spinner

if TYPE_CHECKING:
    from .args import CliConfig

EXTENSION_FORMATS = {'.csv': 'csv', '.json': 'json', '.jsonl': 'jsonl'}
DEFAULT_STRUCTURED_FORMAT = 'jsonl'

TABLE_DEFAULT_FIELDS = ('title', 'company', 'place', 'date', 'link')
TABLE_LIST_SEPARATOR = ', '
STRUCTURED_LIST_SEPARATOR = '|'

TABLE_COLUMN_SEPARATOR = '  '
TABLE_MIN_COLUMN_WIDTH = 8
TABLE_ELLIPSIS = '…'

# Fields whose values are URLs, rendered as clickable terminal hyperlinks in the table.
HYPERLINK_FIELDS = ('link', 'apply_link', 'company_link', 'company_img_link')

ANSI_LINK = '\x1b[36m'

# Curated colours for the fields that carry the most meaning at a glance.
_SIGNATURE_FIELD_COLORS = {
    'title': ANSI_BOLD,
    'company': ANSI_GREEN,
    'place': ANSI_YELLOW,
    'date': ANSI_MAGENTA,
}

# Cycled across the remaining non-link fields so each gets a stable, distinct colour.
_FIELD_COLOR_PALETTE = (
    ANSI_BLUE, ANSI_RED, ANSI_BRIGHT_GREEN, ANSI_BRIGHT_YELLOW,
    ANSI_BRIGHT_BLUE, ANSI_BRIGHT_MAGENTA, ANSI_BRIGHT_RED,
)


def _build_field_colors() -> dict[str, str]:
    """Assign a stable colour to every non-link field; link fields keep cyan elsewhere."""
    colors: dict[str, str] = {}
    palette_index = 0
    for name in EventData._fields:
        if name in HYPERLINK_FIELDS:
            continue
        if name in _SIGNATURE_FIELD_COLORS:
            colors[name] = _SIGNATURE_FIELD_COLORS[name]
        else:
            colors[name] = _FIELD_COLOR_PALETTE[palette_index % len(_FIELD_COLOR_PALETTE)]
            palette_index += 1
    return colors


# Per-field ANSI colours applied to table values. The hyperlink fields keep their own
# cyan styling instead of a colour from here.
FIELD_COLORS = _build_field_colors()

_WHITESPACE_RE = re.compile(r'\s+')


class OutputConfigError(ValueError):
    """Raised when the requested output configuration cannot be satisfied."""


def _collapse_whitespace(value: str) -> str:
    """Collapse every run of whitespace (newlines and tabs included) to one space, then strip."""
    return _WHITESPACE_RE.sub(' ', value).strip()


def _prepare_value(value: Any, raw: bool) -> Any:
    """Return a value ready for serialization, collapsing whitespace unless raw is set.

    Strings are collapsed; lists have each element stringified and collapsed; every other
    type is returned unchanged so the serializer handles it.
    """
    if isinstance(value, str):
        return value if raw else _collapse_whitespace(value)
    if isinstance(value, list):
        items = [str(item) for item in value]
        if not raw:
            items = [_collapse_whitespace(item) for item in items]
        return items
    return value


def resolve_format(config: 'CliConfig') -> str:
    """Resolve the effective output format from the explicit flag, the path, or the tty."""
    destination_is_file = bool(config.out_path) and config.out_path != '-'

    if config.out_format:
        resolved = config.out_format
    elif destination_is_file:
        extension = Path(config.out_path or '').suffix.lower()
        resolved = EXTENSION_FORMATS.get(extension, DEFAULT_STRUCTURED_FORMAT)
    else:
        resolved = 'table' if sys.stdout.isatty() else DEFAULT_STRUCTURED_FORMAT

    # A table only makes sense on stdout; a file destination downgrades it.
    if resolved == 'table' and destination_is_file:
        resolved = DEFAULT_STRUCTURED_FORMAT

    return resolved


def resolve_fields(config: 'CliConfig', output_format: str) -> list[str]:
    """Resolve the ordered list of fields to emit for the given format."""
    available = list(EventData._fields)

    if config.fields:
        for name in config.fields:
            if name not in available:
                allowed = ', '.join(available)
                raise OutputConfigError(
                    f"unknown field '{name}' (choose from {allowed})")
        return list(config.fields)

    if config.all_fields:
        return available

    if output_format == 'table':
        return list(TABLE_DEFAULT_FIELDS)

    return available


def _use_color(config: 'CliConfig') -> bool:
    """Decide whether ANSI colour may be emitted, honouring --no-color, NO_COLOR and the tty."""
    if config.no_color or os.environ.get('NO_COLOR'):
        return False
    return sys.stdout.isatty()


def _use_hyperlinks() -> bool:
    """Decide whether OSC 8 terminal hyperlinks may be emitted, gated only on the tty."""
    return sys.stdout.isatty()


def _hyperlink(url: str, label: str) -> str:
    """Wrap a label in an OSC 8 hyperlink pointing at url.

    Control characters that would corrupt the escape envelope are stripped from the
    target. The escape bytes are zero-width, so this must be applied after any width
    computation to keep column alignment intact.
    """
    target = url.replace('\x1b', '').replace('\n', '').replace('\r', '')
    return f'\x1b]8;;{target}\x1b\\{label}\x1b]8;;\x1b\\'


def _compact_url(url: str) -> str:
    """Shorten a URL to a compact host/…/last-segment label, leaving non-URLs unchanged."""
    parts = urlsplit(url)
    if not parts.netloc:
        return url

    host = parts.netloc[4:] if parts.netloc.startswith('www.') else parts.netloc
    segments = [segment for segment in parts.path.split('/') if segment]

    if len(segments) > 1:
        return f'{host}/{TABLE_ELLIPSIS}/{segments[-1]}'
    if len(segments) == 1:
        return f'{host}/{segments[0]}'
    return host


class Writer:
    """Common interface every output writer implements."""

    def begin(self) -> None:
        """Open the destination and emit any preamble."""
        raise NotImplementedError

    def write(self, data: EventData) -> None:
        """Emit a single record."""
        raise NotImplementedError

    def end(self) -> None:
        """Emit any postamble and close the destination."""
        raise NotImplementedError


class _FileBackedWriter(Writer):
    """Base for writers that stream to stdout or to a path opened for the run's duration."""

    def __init__(self, fields: list[str], raw: bool, out_path: str | None,
                 spinner: Spinner) -> None:
        self._fields = fields
        self._raw = raw
        self._out_path = out_path
        self._spinner = spinner
        self._stream: TextIO | None = None
        self._owns_stream = False

    def _open(self) -> None:
        if self._out_path and self._out_path != '-':
            self._stream = open(self._out_path, 'w', encoding='utf-8', newline='')
            self._owns_stream = True
        else:
            self._stream = sys.stdout
            self._owns_stream = False

    def _close(self) -> None:
        if self._owns_stream and self._stream is not None:
            self._stream.close()
        self._stream = None

    def _record(self, data: EventData) -> dict[str, Any]:
        """Project the event onto the selected fields with preprocessing applied."""
        source = data._asdict()
        return {name: _prepare_value(source[name], self._raw) for name in self._fields}


class JsonlWriter(_FileBackedWriter):
    """One compact JSON object per line."""

    def begin(self) -> None:
        self._open()

    def write(self, data: EventData) -> None:
        assert self._stream is not None
        with self._spinner.pause():
            self._stream.write(json.dumps(self._record(data), ensure_ascii=False))
            self._stream.write('\n')
            self._stream.flush()

    def end(self) -> None:
        self._close()


class JsonWriter(_FileBackedWriter):
    """A single well-formed JSON array, streamed element by element."""

    def __init__(self, fields: list[str], raw: bool, out_path: str | None,
                 spinner: Spinner) -> None:
        super().__init__(fields, raw, out_path, spinner)
        self._first = True

    def begin(self) -> None:
        self._open()
        assert self._stream is not None
        self._first = True
        self._stream.write('[')

    def write(self, data: EventData) -> None:
        assert self._stream is not None
        text = json.dumps(self._record(data), ensure_ascii=False, indent=2)
        indented = '\n'.join('  ' + line for line in text.split('\n'))
        with self._spinner.pause():
            self._stream.write('\n' if self._first else ',\n')
            self._stream.write(indented)
            self._first = False
            self._stream.flush()

    def end(self) -> None:
        assert self._stream is not None
        if not self._first:
            self._stream.write('\n')
        self._stream.write(']\n')
        self._close()


class CsvWriter(_FileBackedWriter):
    """Comma-delimited rows with a header, list values joined by a pipe."""

    def __init__(self, fields: list[str], raw: bool, out_path: str | None,
                 spinner: Spinner) -> None:
        super().__init__(fields, raw, out_path, spinner)
        self._csv_writer: Any = None

    def begin(self) -> None:
        self._open()
        self._csv_writer = csv.writer(self._stream)
        self._csv_writer.writerow(self._fields)

    def write(self, data: EventData) -> None:
        record = self._record(data)
        row: list[Any] = []
        for name in self._fields:
            value = record[name]
            if isinstance(value, list):
                row.append(STRUCTURED_LIST_SEPARATOR.join(value))
            elif value is None:
                row.append('')
            else:
                row.append(value)
        with self._spinner.pause():
            self._csv_writer.writerow(row)

    def end(self) -> None:
        self._csv_writer = None
        self._close()


def _stringify_cell(value: Any) -> str:
    """Render a prepared value as a single human-readable string for table output."""
    if isinstance(value, list):
        return TABLE_LIST_SEPARATOR.join(value)
    if value is None:
        return ''
    return str(value)


class TableWriter(Writer):
    """Human-oriented streaming table for stdout, columnar or vertical."""

    def __init__(self, fields: list[str], raw: bool, vertical: bool, use_color: bool,
                 use_hyperlinks: bool, spinner: Spinner) -> None:
        self._fields = fields
        self._raw = raw
        self._forced_vertical = vertical
        self._use_color = use_color
        self._use_hyperlinks = use_hyperlinks
        self._spinner = spinner
        self._vertical = vertical
        self._widths: list[int] = []
        self._record_index = 0
        self._current_section: tuple[str, str] | None = None
        self._section_job_count = 0

    def _prepared(self, data: EventData) -> dict[str, Any]:
        source = data._asdict()
        return {name: _prepare_value(source[name], self._raw) for name in self._fields}

    def _decorate(self, text: str) -> str:
        if self._use_color:
            return f'{ANSI_BOLD}{text}{ANSI_RESET}'
        return text

    @staticmethod
    def _truncate(text: str, width: int) -> str:
        if width <= 0:
            return ''
        if len(text) <= width:
            return text
        if width == 1:
            return text[:1]
        return text[:width - 1] + TABLE_ELLIPSIS

    @staticmethod
    def _fit(text: str, width: int) -> str:
        return TableWriter._truncate(text, width).ljust(width)

    def _compute_layout(self) -> None:
        columns = shutil.get_terminal_size((80, 24)).columns
        field_count = len(self._fields)
        separators = len(TABLE_COLUMN_SEPARATOR) * max(field_count - 1, 0)
        minimum = field_count * TABLE_MIN_COLUMN_WIDTH + separators

        if self._forced_vertical or columns < minimum:
            self._vertical = True
            return

        self._vertical = False
        available = max(columns - separators, field_count)
        base = available // field_count
        remainder = available % field_count
        self._widths = [base + (1 if i < remainder else 0) for i in range(field_count)]

    def begin(self) -> None:
        self._record_index = 0
        self._compute_layout()

    def _begin_section(self) -> None:
        """Open a new (query, location) section: in columnar mode reprint the header so
        each section reads on its own. The inter-section margin is owned by Feedback,
        printed on stderr before the section's opener line."""
        if self._vertical:
            return

        header = TABLE_COLUMN_SEPARATOR.join(
            self._header_cell(name, width)
            for name, width in zip(self._fields, self._widths))
        rule = TABLE_COLUMN_SEPARATOR.join('─' * width for width in self._widths)
        with self._spinner.pause():
            print(header, flush=True)
            print(rule, flush=True)

    def _header_cell(self, name: str, width: int) -> str:
        if self._use_color:
            # Bold only the visible label; pad outside the envelope to preserve alignment.
            label = self._truncate(name, width)
            pad = ' ' * max(width - len(label), 0)
            return f'{ANSI_BOLD}{label}{ANSI_RESET}' + pad
        return self._fit(name, width)

    def write(self, data: EventData) -> None:
        section = (data.query, data.location)
        if section != self._current_section:
            self._current_section = section
            self._section_job_count = 0
            self._begin_section()

        self._record_index += 1
        record = self._prepared(data)
        if self._vertical:
            self._write_vertical(record)
        else:
            self._write_row(record)

    def _link_style(self, cell: str) -> str:
        if self._use_color:
            return f'{ANSI_LINK}{cell}{ANSI_RESET}'
        return cell

    def _write_row(self, record: dict[str, Any]) -> None:
        cells: list[str] = []
        for name, width in zip(self._fields, self._widths):
            value = _stringify_cell(record[name])
            if name in HYPERLINK_FIELDS and value and self._use_hyperlinks:
                # Keep the OSC 8 envelope around the visible label only, so the terminal's
                # hyperlink underline does not extend across the column padding.
                label = self._truncate(_compact_url(value), width)
                pad = ' ' * max(width - len(label), 0)
                styled = f'{ANSI_LINK}{label}{ANSI_RESET}' if self._use_color else label
                cells.append(_hyperlink(value, styled) + pad)
            elif name in HYPERLINK_FIELDS and value:
                cells.append(self._link_style(self._fit(value, width)))
            elif self._use_color and name in FIELD_COLORS:
                # Colour only the visible truncated text; keep the padding outside the
                # escape envelope so alignment is unaffected.
                label = self._truncate(value, width)
                pad = ' ' * max(width - len(label), 0)
                cells.append(f'{FIELD_COLORS[name]}{label}{ANSI_RESET}' + pad)
            else:
                cells.append(self._fit(value, width))
        with self._spinner.pause():
            print(TABLE_COLUMN_SEPARATOR.join(cells), flush=True)

    def _write_vertical(self, record: dict[str, Any]) -> None:
        key_width = max(len(name) for name in self._fields)
        with self._spinner.pause():
            if self._section_job_count > 0:
                print(flush=True)
            print(self._decorate(f'── Job {self._record_index} ──'), flush=True)
            for name in self._fields:
                value = _stringify_cell(record[name])
                if name in HYPERLINK_FIELDS and value:
                    rendered = self._link_style(value)
                    if self._use_hyperlinks:
                        rendered = _hyperlink(value, rendered)
                elif self._use_color and name in FIELD_COLORS and value:
                    rendered = f'{FIELD_COLORS[name]}{value}{ANSI_RESET}'
                else:
                    rendered = value
                print(f'{name.ljust(key_width)}: {rendered}', flush=True)
        self._section_job_count += 1

    def end(self) -> None:
        return None


def create_writer(config: 'CliConfig', spinner: Spinner) -> Writer:
    """Resolve format and fields from the config and construct the matching writer."""
    output_format = resolve_format(config)
    fields = resolve_fields(config, output_format)

    if output_format == 'jsonl':
        return JsonlWriter(fields, config.raw, config.out_path, spinner)
    if output_format == 'json':
        return JsonWriter(fields, config.raw, config.out_path, spinner)
    if output_format == 'csv':
        return CsvWriter(fields, config.raw, config.out_path, spinner)
    if output_format == 'table':
        return TableWriter(
            fields, config.raw, config.vertical, _use_color(config), _use_hyperlinks(),
            spinner)

    raise OutputConfigError(f"unsupported output format '{output_format}'")
