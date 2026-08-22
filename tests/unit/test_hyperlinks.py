"""Offline tests for CLI terminal hyperlinks (OSC 8) in table output.

Writers and helpers are driven directly: no network, no browser, no tty required.
"""
from __future__ import annotations

import io

from linkedin_jobs_scraper.cli.output import (
    TableWriter,
    _compact_url,
    _hyperlink,
)
from linkedin_jobs_scraper.cli.spinner import Spinner
from linkedin_jobs_scraper.events import EventData


def _disabled_spinner() -> Spinner:
    return Spinner(io.StringIO(), enabled=False)


# --- _compact_url ---------------------------------------------------------

def test_compact_url_job_link() -> None:
    assert _compact_url('https://www.linkedin.com/jobs/view/4438317294') == \
        'linkedin.com/…/4438317294'


def test_compact_url_company_link_trailing_slash() -> None:
    assert _compact_url('https://www.linkedin.com/company/morando/') == \
        'linkedin.com/…/morando'


def test_compact_url_external_apply_link() -> None:
    assert _compact_url('https://boards.greenhouse.io/acme/jobs/12345') == \
        'boards.greenhouse.io/…/12345'


def test_compact_url_single_segment() -> None:
    assert _compact_url('https://www.linkedin.com/jobs') == 'linkedin.com/jobs'


def test_compact_url_host_only() -> None:
    assert _compact_url('https://www.linkedin.com/') == 'linkedin.com'
    assert _compact_url('https://linkedin.com') == 'linkedin.com'


def test_compact_url_non_url_unchanged() -> None:
    assert _compact_url('not a url') == 'not a url'
    assert _compact_url('') == ''


# --- _hyperlink -----------------------------------------------------------

def test_hyperlink_envelope() -> None:
    url = 'https://example.com/jobs/view/1'
    assert _hyperlink(url, 'label') == \
        f'\x1b]8;;{url}\x1b\\label\x1b]8;;\x1b\\'


def test_hyperlink_strips_control_chars_from_target() -> None:
    result = _hyperlink('https://ex\x1bample\n.com\r/x', 'label')
    assert result == '\x1b]8;;https://example.com/x\x1b\\label\x1b]8;;\x1b\\'


def test_hyperlink_label_passes_through_verbatim() -> None:
    label = 'has \x1b[4;36m colour \x1b[0m'
    result = _hyperlink('https://example.com', label)
    assert label in result


# --- TableWriter-level ----------------------------------------------------

def _record() -> EventData:
    return EventData(
        query='python',
        location='Remote',
        job_id='123',
        job_index=0,
        link='https://www.linkedin.com/jobs/view/4438317294',
        apply_link='',
        title='Engineer',
        company='Acme',
        company_link='',
        company_employee_count='',
        company_img_link='',
        place='Remote',
        description='',
        description_html='',
        date='2026-08-21',
        date_text='1 day ago',
        insights=[],
    )


def _columnar_writer(use_hyperlinks: bool) -> TableWriter:
    writer = TableWriter(
        fields=['title', 'link'],
        raw=False,
        vertical=False,
        use_color=False,
        use_hyperlinks=use_hyperlinks,
        spinner=_disabled_spinner(),
    )
    # Force a wide columnar layout without touching the terminal.
    writer._vertical = False
    writer._widths = [40, 60]
    return writer


def test_table_row_with_hyperlinks(capsys) -> None:
    writer = _columnar_writer(use_hyperlinks=True)
    writer.write(_record())
    out = capsys.readouterr().out
    # Full URL is the click target inside the OSC 8 envelope.
    assert '\x1b]8;;https://www.linkedin.com/jobs/view/4438317294\x1b\\' in out
    assert '\x1b]8;;\x1b\\' in out
    # Visible label is compacted.
    assert 'linkedin.com/…/4438317294' in out
    # The envelope wraps only the visible label: it closes right after the label,
    # with the column padding placed OUTSIDE the hyperlink.
    assert '\x1b\\linkedin.com/…/4438317294\x1b]8;;\x1b\\' in out
    assert 'linkedin.com/…/4438317294\x1b]8;;\x1b\\ ' in out


def test_table_row_without_hyperlinks(capsys) -> None:
    writer = _columnar_writer(use_hyperlinks=False)
    writer.write(_record())
    out = capsys.readouterr().out
    assert '\x1b]8;;' not in out
    # Raw, uncompacted URL is shown.
    assert 'https://www.linkedin.com/jobs/view/4438317294' in out
    assert 'linkedin.com/…/' not in out
