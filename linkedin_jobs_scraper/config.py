import os
import logging


class Config:
    LI_AT_COOKIE = os.environ.get('LI_AT_COOKIE')

    # LinkedIn's remember me credential, and the browser id it was issued to. Supplied
    # together they replace LI_AT_COOKIE with something that lasts a year: the scraper has
    # a session minted from them instead of being handed one that will be retired.
    LI_RM_COOKIE = os.environ.get('LI_RM_COOKIE')
    LI_BCOOKIE = os.environ.get('LI_BCOOKIE')

    LOGGER_NAMESPACE = 'li:scraper'

    _level = logging.INFO

    if 'LOG_LEVEL' in os.environ:
        _level_env = os.environ['LOG_LEVEL'].upper().strip()

        if _level_env == 'DEBUG':
            _level = logging.DEBUG
        elif _level_env == 'INFO':
            _level = logging.INFO
        elif _level_env == 'WARN' or _level_env == 'WARNING':
            _level = logging.WARN
        elif _level_env == 'ERROR':
            _level = logging.ERROR
        elif _level_env == 'FATAL':
            _level = logging.FATAL

    LOGGER_LEVEL = _level
