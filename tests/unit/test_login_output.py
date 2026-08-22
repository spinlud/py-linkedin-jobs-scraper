"""Offline tests for the login subcommand's terminal output.

No network, no browser, no credentials. Only print_credentials formatting is exercised.
"""
from __future__ import annotations

from linkedin_jobs_scraper.cli.color import Colorizer
from linkedin_jobs_scraper.login import print_credentials

PROFILE = '/home/user/.linkedin-jobs-scraper'


def test_print_credentials_with_remember_me_pair(capsys):
    credentials = {
        'li_at': 'AQED-session',
        'li_rm': 'AQED-remember',
        'bcookie': 'v=2&"abc"&def',
    }

    print_credentials(PROFILE, credentials, Colorizer(False))
    out = capsys.readouterr().out

    assert 'li_at=' not in out
    assert 'Signed in. The profile now carries the session.' in out
    assert 'lijs jobs ' in out
    assert 'lijs job ' in out
    assert '--chrome-user-data-dir' in out
    assert "LI_RM_COOKIE='AQED-remember'" in out
    assert "LI_BCOOKIE='v=2&\"abc\"&def'" in out


def test_print_credentials_without_remember_me_pair(capsys):
    credentials = {'li_at': 'AQED-session', 'li_rm': None, 'bcookie': None}

    print_credentials(PROFILE, credentials, Colorizer(False))
    out = capsys.readouterr().out

    assert 'li_at=' not in out
    assert 'No remember me cookie was issued' in out
    assert 'LI_RM_COOKIE' not in out


def test_print_credentials_colors_tokens_when_enabled(capsys):
    credentials = {
        'li_at': 'AQED-session',
        'li_rm': 'AQED-remember',
        'bcookie': 'v=2&"abc"&def',
    }

    print_credentials(PROFILE, credentials, Colorizer(True))
    out = capsys.readouterr().out

    # Cyan wraps lijs and the env var names, orange wraps the subcommand token and the '='.
    assert '\x1b[36m' in out
    assert '\x1b[38;5;208m' in out
    # Name and '=' are now separated by ANSI codes, so the raw substring no longer appears.
    assert 'LI_RM_COOKIE=' not in out


def test_print_credentials_defaults_to_plain_output(capsys):
    credentials = {'li_at': 'AQED-session', 'li_rm': 'r', 'bcookie': 'b'}

    print_credentials(PROFILE, credentials)
    out = capsys.readouterr().out

    assert '\x1b[' not in out
