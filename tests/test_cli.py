#!/usr/bin/env python
"""Live end-to-end tests for the command line interface.

The CLI is driven as a subprocess against the real LinkedIn site, mirroring the
programmatic live suite. Credentials come from the environment (the LI_RM_COOKIE +
LI_BCOOKIE pair, LI_AT_COOKIE, or LI_CHROME_USER_DATA_DIR pointing at a seeded Chrome
profile); without them the whole module is skipped so a local run without secrets is
clean. Data is requested as jsonl on stdout and parsed line by line, while human feedback
lands on stderr.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_TIMEOUT_SECONDS = 600

# Fields every scraped record must carry, with a non-empty value.
REQUIRED_NON_EMPTY_FIELDS = ('job_id', 'title', 'company', 'link')

_JOBS_VIEW_RE = re.compile(r'/jobs/view/')
_DIGITS_RE = re.compile(r'\d+')

# A single-job scrape captured live from the search run, so the follow-up test targets a
# currently-live posting rather than a hardcoded id LinkedIn may have removed.
captured_job_ids: list[str] = []


def _has_credentials() -> bool:
    if os.environ.get('LI_CHROME_USER_DATA_DIR'):
        return True
    if os.environ.get('LI_RM_COOKIE') and os.environ.get('LI_BCOOKIE'):
        return True
    return bool(os.environ.get('LI_AT_COOKIE'))


pytestmark = pytest.mark.skipif(
    not _has_credentials(),
    reason='no LinkedIn credentials in the environment (LI_RM_COOKIE + LI_BCOOKIE, LI_AT_COOKIE, or LI_CHROME_USER_DATA_DIR)')


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the CLI as a module subprocess from the repo root, capturing stdout and stderr.

    The captured streams are echoed back to the terminal so a live run is observable; the
    captured text is still what the assertions read.
    """
    # A seeded Chrome profile is an alternative to env cookies; pass it through to the CLI.
    profile_dir = os.environ.get('LI_CHROME_USER_DATA_DIR')
    extra_args = ['--chrome-user-data-dir', profile_dir] if profile_dir else []
    result = subprocess.run(
        [sys.executable, '-m', 'linkedin_jobs_scraper', *args, *extra_args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=os.environ.copy(),
        timeout=CLI_TIMEOUT_SECONDS,
    )
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result


def _parse_jsonl(stdout: str) -> list[dict]:
    """Parse non-blank stdout lines as jsonl, asserting each is a JSON object."""
    records: list[dict] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        assert isinstance(record, dict)
        records.append(record)
    return records


def _numeric_id(value: str) -> str:
    """Extract the numeric id from a bare id or a '/jobs/view/<id>' url."""
    match = _DIGITS_RE.search(value)
    assert match is not None, value
    return match.group(0)


def _assert_record_shape(record: dict) -> None:
    """Validate a parsed jsonl record has sane key fields, without EventData machinery."""
    for field in REQUIRED_NON_EMPTY_FIELDS:
        assert field in record, field
        assert isinstance(record[field], str)
        assert len(record[field]) > 0, field
    assert _JOBS_VIEW_RE.search(record['link'])


def test_jobs_search() -> None:
    result = _run_cli(
        'jobs', 'Software Engineer',
        '--location', 'United States',
        '--limit', '5',
        '-f', 'jsonl',
        '--no-color',
    )

    assert result.returncode == 0, result.stderr

    records = _parse_jsonl(result.stdout)
    assert len(records) >= 1

    for record in records:
        _assert_record_shape(record)

    captured_job_ids.append(_numeric_id(records[0]['job_id']))


def test_job_single() -> None:
    if not captured_job_ids:
        pytest.skip('no job id captured from the search test run')

    job_id = captured_job_ids[0]

    result = _run_cli('job', job_id, '-f', 'jsonl', '--no-color')

    assert result.returncode == 0, result.stderr

    records = _parse_jsonl(result.stdout)
    assert len(records) == 1
    assert _numeric_id(records[0]['job_id']) == job_id


def test_job_not_found() -> None:
    missing_id = '9999999999999'

    result = _run_cli('job', missing_id, '-f', 'jsonl', '--no-color')

    assert result.returncode == 3, result.stderr

    records = _parse_jsonl(result.stdout)
    assert len(records) == 0

    assert 'job not found' in result.stderr
    assert missing_id in result.stderr
