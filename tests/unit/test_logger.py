"""Offline tests for the `utils.logger` helpers."""
import inspect
import logging
from collections.abc import Callable

import pytest

from linkedin_jobs_scraper.config import Config
from linkedin_jobs_scraper.utils import logger


@pytest.fixture(autouse=True)
def _capture_debug(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger=Config.LOGGER_NAMESPACE)


def test_single_string_renders_plain(caplog: pytest.LogCaptureFixture) -> None:
    logger.info('A Chrome profile cannot be shared')
    assert caplog.records[-1].getMessage() == 'A Chrome profile cannot be shared'


def test_multiple_args_are_tab_joined(caplog: pytest.LogCaptureFixture) -> None:
    logger.warn('first', 'second', 'third')
    assert caplog.records[-1].getMessage() == 'first\tsecond\tthird'


def test_non_string_args_use_str(caplog: pytest.LogCaptureFixture) -> None:
    logger.debug('failed', ValueError('boom'), [1, 2])
    assert caplog.records[-1].getMessage() == 'failed\tboom\t[1, 2]'


def test_long_arg_is_truncated_but_short_sibling_is_not(caplog: pytest.LogCaptureFixture) -> None:
    long_text = 'x' * (logger.max_length + 50)
    logger.info('short', long_text)
    short_part, long_part = caplog.records[-1].getMessage().split('\t')
    assert short_part == 'short'
    assert long_part == 'x' * logger.max_length + '...'


def test_arg_at_max_length_is_not_truncated(caplog: pytest.LogCaptureFixture) -> None:
    text = 'y' * logger.max_length
    logger.info(text)
    assert caplog.records[-1].getMessage() == text


@pytest.mark.parametrize('helper', [logger.debug, logger.info, logger.warn, logger.error])
def test_record_points_at_caller(
        helper: Callable[..., None], caplog: pytest.LogCaptureFixture) -> None:
    frame = inspect.currentframe()
    assert frame is not None
    line = frame.f_lineno + 1
    helper('where')
    record = caplog.records[-1]
    assert record.funcName == 'test_record_points_at_caller'
    assert record.lineno == line
    assert record.pathname == __file__


def test_error_attaches_exc_info_by_default(caplog: pytest.LogCaptureFixture) -> None:
    try:
        raise RuntimeError('kaboom')
    except RuntimeError:
        logger.error('failed')
    record = caplog.records[-1]
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None
    assert record.exc_info[0] is RuntimeError


def test_error_without_exc_info(caplog: pytest.LogCaptureFixture) -> None:
    try:
        raise RuntimeError('kaboom')
    except RuntimeError:
        logger.error('failed', exc_info=False)
    assert not caplog.records[-1].exc_info
    assert 'Traceback' not in caplog.text


def test_percent_in_message_does_not_raise(
        caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]) -> None:
    logger.info('100% done %s %d', 'extra')
    assert caplog.records[-1].getMessage() == '100% done %s %d\textra'
    assert '100% done %s %d\textra' in caplog.text
    assert 'Logging error' not in capsys.readouterr().err
