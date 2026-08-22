"""Offline tests for CLI output writers (linkedin_jobs_scraper.cli.output).

Writers are driven directly with synthetic EventData: no network, no browser.
"""
from __future__ import annotations

import contextlib
import csv
import io
import json
import re
from typing import Any

import pytest

from linkedin_jobs_scraper.cli.args import CliConfig
from linkedin_jobs_scraper.cli import output as output_module
from linkedin_jobs_scraper.cli.output import (
    OutputConfigError,
    TABLE_DEFAULT_FIELDS,
    TableWriter,
    create_writer,
    resolve_fields,
    resolve_format,
)
from linkedin_jobs_scraper.cli.spinner import Spinner
from linkedin_jobs_scraper.events import EventData

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def _disabled_spinner() -> Spinner:
    """A no-op spinner so writer output is captured verbatim in tests."""
    return Spinner(io.StringIO(), enabled=False)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub('', text)


class FakeTty:
    """Minimal stdout stand-in whose tty-ness is fixed."""

    def __init__(self, is_tty: bool) -> None:
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


def _config(**overrides: Any) -> CliConfig:
    return CliConfig(subcommand='jobs', **overrides)


def _sample_record() -> EventData:
    return EventData(
        query='python',
        location='Remote',
        job_id='123',
        job_index=0,
        link='https://example.com/jobs/view/123',
        apply_link='',
        title='Engineer, Backend',
        company='Acme, "Inc"',
        company_link='',
        company_employee_count='',
        company_img_link='',
        place='New York',
        description='line one,\n\ttabbed "quoted" line two',
        description_html='',
        date='2026-08-21',
        date_text='1 day ago',
        insights=['Remote', 'Full-time'],
    )


def _set_stdout_tty(monkeypatch: pytest.MonkeyPatch, is_tty: bool) -> None:
    monkeypatch.setattr(output_module.sys, 'stdout', FakeTty(is_tty))


# --- format resolution ---------------------------------------------------

def test_explicit_format_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_stdout_tty(monkeypatch, True)
    assert resolve_format(_config(out_format='csv')) == 'csv'


def test_format_from_extension() -> None:
    assert resolve_format(_config(out_path='x.csv')) == 'csv'
    assert resolve_format(_config(out_path='x.json')) == 'json'
    assert resolve_format(_config(out_path='x.txt')) == 'jsonl'


def test_format_from_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_stdout_tty(monkeypatch, True)
    assert resolve_format(_config()) == 'table'
    _set_stdout_tty(monkeypatch, False)
    assert resolve_format(_config()) == 'jsonl'


def test_table_downgrades_to_jsonl_for_file() -> None:
    assert resolve_format(_config(out_format='table', out_path='out.txt')) == 'jsonl'


# --- jsonl ----------------------------------------------------------------

def test_jsonl_lines_are_valid_json_and_collapse_newlines(tmp_path) -> None:
    path = tmp_path / 'out.jsonl'
    writer = create_writer(_config(out_path=str(path)), _disabled_spinner())
    writer.begin()
    writer.write(_sample_record())
    writer.end()

    lines = path.read_text(encoding='utf-8').splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert '\n' not in record['description']
    assert '\t' not in record['description']
    assert record['insights'] == ['Remote', 'Full-time']


# --- json -----------------------------------------------------------------

def test_json_output_is_an_array(tmp_path) -> None:
    path = tmp_path / 'out.json'
    writer = create_writer(_config(out_path=str(path)), _disabled_spinner())
    writer.begin()
    writer.write(_sample_record())
    writer.write(_sample_record())
    writer.end()

    parsed = json.loads(path.read_text(encoding='utf-8'))
    assert isinstance(parsed, list)
    assert len(parsed) == 2


def test_json_empty_is_empty_array(tmp_path) -> None:
    path = tmp_path / 'out.json'
    writer = create_writer(_config(out_path=str(path)), _disabled_spinner())
    writer.begin()
    writer.end()

    assert json.loads(path.read_text(encoding='utf-8')) == []


# --- csv ------------------------------------------------------------------

def test_csv_header_and_roundtrip(tmp_path) -> None:
    path = tmp_path / 'out.csv'
    writer = create_writer(_config(out_path=str(path), all_fields=True), _disabled_spinner())
    writer.begin()
    writer.write(_sample_record())
    writer.end()

    with path.open(encoding='utf-8', newline='') as handle:
        rows = list(csv.reader(handle))

    header = rows[0]
    assert header == list(EventData._fields)
    row = dict(zip(header, rows[1]))
    # Insights joined by a pipe.
    assert row['insights'] == 'Remote|Full-time'
    # Comma and quotes survive the csv round-trip; newline collapsed by default.
    assert row['company'] == 'Acme, "Inc"'
    assert '\n' not in row['description']


def test_csv_raw_preserves_newline(tmp_path) -> None:
    path = tmp_path / 'out.csv'
    writer = create_writer(_config(out_path=str(path), all_fields=True, raw=True), _disabled_spinner())
    writer.begin()
    writer.write(_sample_record())
    writer.end()

    with path.open(encoding='utf-8', newline='') as handle:
        rows = list(csv.reader(handle))
    row = dict(zip(rows[0], rows[1]))
    assert '\n' in row['description']


# --- field selection ------------------------------------------------------

def test_structured_default_selects_all_fields() -> None:
    fields = resolve_fields(_config(), 'jsonl')
    assert fields == list(EventData._fields)
    assert len(fields) == 17


def test_table_default_selects_curated_five() -> None:
    assert resolve_fields(_config(), 'table') == list(TABLE_DEFAULT_FIELDS)


def test_explicit_fields_selection() -> None:
    assert resolve_fields(_config(fields=['title', 'company']), 'jsonl') == ['title', 'company']


def test_unknown_field_raises() -> None:
    with pytest.raises(OutputConfigError):
        resolve_fields(_config(fields=['title', 'bogus']), 'jsonl')


# --- table layout ---------------------------------------------------------

def _fake_terminal_size(monkeypatch: pytest.MonkeyPatch, columns: int) -> None:
    monkeypatch.setattr(
        output_module.shutil, 'get_terminal_size',
        lambda fallback=(80, 24): __import__('os').terminal_size((columns, 24)))


def test_table_narrow_is_vertical(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    _fake_terminal_size(monkeypatch, 20)
    writer = create_writer(_config(out_format='table', no_color=True), _disabled_spinner())
    writer.begin()
    writer.write(_sample_record())
    writer.end()
    out = capsys.readouterr().out
    assert '── Job 1 ──' in out


def test_table_wide_is_columnar(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    _fake_terminal_size(monkeypatch, 200)
    writer = create_writer(_config(out_format='table', no_color=True), _disabled_spinner())
    writer.begin()
    writer.write(_sample_record())
    writer.end()
    out = capsys.readouterr().out
    assert '── Job 1 ──' not in out
    assert 'title' in out


def test_table_vertical_flag_forces_vertical(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    _fake_terminal_size(monkeypatch, 200)
    writer = create_writer(_config(out_format='table', vertical=True, no_color=True), _disabled_spinner())
    writer.begin()
    writer.write(_sample_record())
    writer.end()
    out = capsys.readouterr().out
    assert '── Job 1 ──' in out


# --- table colours --------------------------------------------------------

def _color_writer(fields: list[str], use_color: bool) -> TableWriter:
    writer = TableWriter(
        fields=fields,
        raw=False,
        vertical=False,
        use_color=use_color,
        use_hyperlinks=False,
        spinner=_disabled_spinner(),
    )
    # Force a wide columnar layout without touching the terminal.
    writer._vertical = False
    writer._widths = [30] * len(fields)
    return writer


def _colored_row(fields: list[str]) -> str:
    writer = _color_writer(fields, use_color=True)
    buffer = io.StringIO()

    with contextlib.redirect_stdout(buffer):
        writer.write(_sample_record())
    return buffer.getvalue()


def test_table_title_cell_is_bold() -> None:
    out = _colored_row(['title'])
    assert '\x1b[1m' in out
    assert '\x1b[0m' in out


def test_table_company_cell_is_green() -> None:
    out = _colored_row(['company'])
    assert '\x1b[32m' in out


def test_table_place_cell_is_yellow() -> None:
    out = _colored_row(['place'])
    assert '\x1b[33m' in out


def test_table_date_cell_is_magenta() -> None:
    out = _colored_row(['date'])
    assert '\x1b[35m' in out


def test_table_link_cell_keeps_cyan() -> None:
    out = _colored_row(['link'])
    assert '\x1b[36m' in out


def test_table_insights_cell_is_coloured() -> None:
    # Previously uncoloured; every non-link field now carries a palette colour.
    out = _colored_row(['insights'])
    assert '\x1b[' in out


def test_table_job_index_cell_is_coloured() -> None:
    out = _colored_row(['job_index'])
    assert '\x1b[' in out


def test_table_every_non_link_field_is_coloured() -> None:
    for name in EventData._fields:
        if name in output_module.HYPERLINK_FIELDS:
            continue
        assert name in output_module.FIELD_COLORS
    for name in output_module.HYPERLINK_FIELDS:
        assert name not in output_module.FIELD_COLORS


def test_table_signature_field_colours() -> None:
    assert output_module.FIELD_COLORS['title'] == '\x1b[1m'
    assert output_module.FIELD_COLORS['company'] == '\x1b[32m'
    assert output_module.FIELD_COLORS['place'] == '\x1b[33m'
    assert output_module.FIELD_COLORS['date'] == '\x1b[35m'


def test_table_header_labels_are_bold() -> None:
    writer = _color_writer(['title', 'company'], use_color=True)
    buffer = io.StringIO()

    with contextlib.redirect_stdout(buffer):
        writer.write(_sample_record())
    header_line = buffer.getvalue().splitlines()[0]
    assert header_line.count('\x1b[1m') == 2


def test_table_colour_preserves_alignment() -> None:
    fields = ['title', 'company', 'place', 'date', 'link']
    colored = _color_writer(fields, use_color=True)
    plain = _color_writer(fields, use_color=False)

    colored_buffer, plain_buffer = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(colored_buffer):
        colored.write(_sample_record())
    with contextlib.redirect_stdout(plain_buffer):
        plain.write(_sample_record())

    assert _strip_ansi(colored_buffer.getvalue()) == plain_buffer.getvalue()


def test_table_no_color_emits_no_escapes() -> None:
    fields = ['title', 'company', 'place', 'date', 'link']
    plain = _color_writer(fields, use_color=False)

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        plain.begin()
        plain.write(_sample_record())
    assert '\x1b[' not in buffer.getvalue()


# --- table sections (lazy header + blank-line separation) -----------------

def _record_at(location: str) -> EventData:
    return _sample_record()._replace(location=location)


def _plain_columnar_writer(fields: list[str]) -> TableWriter:
    writer = TableWriter(
        fields=fields,
        raw=False,
        vertical=False,
        use_color=False,
        use_hyperlinks=False,
        spinner=_disabled_spinner(),
    )
    writer._vertical = False
    writer._widths = [30] * len(fields)
    return writer


def _plain_vertical_writer(fields: list[str]) -> TableWriter:
    writer = TableWriter(
        fields=fields,
        raw=False,
        vertical=True,
        use_color=False,
        use_hyperlinks=False,
        spinner=_disabled_spinner(),
    )
    writer._vertical = True
    return writer


def test_begin_prints_nothing() -> None:
    writer = _plain_columnar_writer(['title', 'company'])
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        writer.begin()
    assert buffer.getvalue() == ''


def test_columnar_header_printed_once_per_section() -> None:
    writer = _plain_columnar_writer(['title', 'company'])
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        writer.write(_record_at('Remote'))
        writer.write(_record_at('Remote'))
    lines = buffer.getvalue().splitlines()

    # Header (labels) + rule, then two rows, and no blank line between them.
    assert lines[0].split() == ['title', 'company']
    assert set(lines[1].replace(' ', '')) == {'─'}
    assert '' not in lines
    # The header text appears exactly once.
    assert sum(1 for line in lines if line.split() == ['title', 'company']) == 1


def test_columnar_new_location_reprints_header_without_inter_section_blank() -> None:
    writer = _plain_columnar_writer(['title', 'company'])
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        writer.write(_record_at('Remote'))
        writer.write(_record_at('Berlin'))
    lines = buffer.getvalue().splitlines()

    # header, rule, row, header, rule, row — the inter-section blank is owned by Feedback.
    assert '' not in lines
    assert lines[0].split() == ['title', 'company']
    assert lines[3].split() == ['title', 'company']
    assert set(lines[4].replace(' ', '')) == {'─'}


def test_vertical_blank_between_jobs_same_section() -> None:
    writer = _plain_vertical_writer(['title', 'company'])
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        writer.write(_record_at('Remote'))
        writer.write(_record_at('Remote'))
    lines = buffer.getvalue().splitlines()

    job_headers = [i for i, line in enumerate(lines) if line.startswith('── Job')]
    assert len(job_headers) == 2
    # No leading blank before the first job.
    assert lines[0].startswith('── Job 1')
    # Exactly one blank line immediately before the second job block.
    second = job_headers[1]
    assert lines[second - 1] == ''
    assert lines[second - 2] != ''
    # Continuous numbering across the section.
    assert lines[second].startswith('── Job 2')


def test_vertical_no_inter_section_blank() -> None:
    writer = _plain_vertical_writer(['title', 'company'])
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        writer.write(_record_at('Remote'))
        writer.write(_record_at('Berlin'))
    lines = buffer.getvalue().splitlines()

    job_headers = [i for i, line in enumerate(lines) if line.startswith('── Job')]
    assert len(job_headers) == 2
    second = job_headers[1]
    # No inter-section blank from the writer; the margin is owned by Feedback.
    assert lines[second - 1] != ''
    assert '' not in lines
