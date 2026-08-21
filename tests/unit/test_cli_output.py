"""Offline tests for CLI output writers (linkedin_jobs_scraper.cli.output).

Writers are driven directly with synthetic EventData: no network, no browser.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any

import pytest

from linkedin_jobs_scraper.cli.args import CliConfig
from linkedin_jobs_scraper.cli import output as output_module
from linkedin_jobs_scraper.cli.output import (
    OutputConfigError,
    TABLE_DEFAULT_FIELDS,
    create_writer,
    resolve_fields,
    resolve_format,
)
from linkedin_jobs_scraper.events import EventData


class FakeTty:
    """Minimal stdout stand-in whose tty-ness is fixed."""

    def __init__(self, is_tty: bool) -> None:
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


def _config(**overrides: Any) -> CliConfig:
    return CliConfig(subcommand='search', **overrides)


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
    writer = create_writer(_config(out_path=str(path)))
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
    writer = create_writer(_config(out_path=str(path)))
    writer.begin()
    writer.write(_sample_record())
    writer.write(_sample_record())
    writer.end()

    parsed = json.loads(path.read_text(encoding='utf-8'))
    assert isinstance(parsed, list)
    assert len(parsed) == 2


def test_json_empty_is_empty_array(tmp_path) -> None:
    path = tmp_path / 'out.json'
    writer = create_writer(_config(out_path=str(path)))
    writer.begin()
    writer.end()

    assert json.loads(path.read_text(encoding='utf-8')) == []


# --- csv ------------------------------------------------------------------

def test_csv_header_and_roundtrip(tmp_path) -> None:
    path = tmp_path / 'out.csv'
    writer = create_writer(_config(out_path=str(path), all_fields=True))
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
    writer = create_writer(_config(out_path=str(path), all_fields=True, raw=True))
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
    writer = create_writer(_config(out_format='table', no_color=True))
    writer.begin()
    writer.write(_sample_record())
    writer.end()
    out = capsys.readouterr().out
    assert '── Job 1 ──' in out


def test_table_wide_is_columnar(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    _fake_terminal_size(monkeypatch, 200)
    writer = create_writer(_config(out_format='table', no_color=True))
    writer.begin()
    writer.write(_sample_record())
    writer.end()
    out = capsys.readouterr().out
    assert '── Job 1 ──' not in out
    assert 'title' in out


def test_table_vertical_flag_forces_vertical(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    _fake_terminal_size(monkeypatch, 200)
    writer = create_writer(_config(out_format='table', vertical=True, no_color=True))
    writer.begin()
    writer.write(_sample_record())
    writer.end()
    out = capsys.readouterr().out
    assert '── Job 1 ──' in out
