"""Offline tests for the login subcommand's error handling (linkedin_jobs_scraper.cli.main).

sign_in is replaced with a stub: no network, no browser, no credentials.
"""
from __future__ import annotations

import importlib
from collections.abc import Callable

import pytest

from linkedin_jobs_scraper.exceptions import ChromedriverResolutionException

# The cli package re-exports the main() function under the submodule's name, so the module
# itself is loaded by path to patch the sign_in it looks up.
main_module = importlib.import_module('linkedin_jobs_scraper.cli.main')

PROFILE = '/home/user/.linkedin-jobs-scraper'
RESOLUTION_MESSAGE = (
    'Unable to obtain driver for chrome. '
    'Pass --chrome-executable-path to use a specific chromedriver.'
)


def _raise(error: Exception) -> Callable[..., None]:
    def _sign_in(*_args: object) -> None:
        raise error
    return _sign_in


def test_login_reports_chromedriver_resolution_failure_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        main_module, 'sign_in', _raise(ChromedriverResolutionException(RESOLUTION_MESSAGE)))

    exit_code = main_module.main(['login', '--chrome-user-data-dir', PROFILE, '--no-color'])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert f'error: {RESOLUTION_MESSAGE}' in captured.err
    assert '--chrome-executable-path' in captured.err
    assert 'Traceback' not in captured.err
    assert 'Traceback' not in captured.out


def test_login_lets_other_exceptions_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, 'sign_in', _raise(RuntimeError('boom')))

    with pytest.raises(RuntimeError, match='boom'):
        main_module.main(['login', '--chrome-user-data-dir', PROFILE, '--no-color'])
