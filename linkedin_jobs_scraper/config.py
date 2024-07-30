import os
import logging
from client import get_cookie

class Config:
    LI_AT_COOKIE = None
    if 'LI_AT_COOKIE' in os.environ:
        LI_AT_COOKIE = os.environ['LI_AT_COOKIE']
    elif 'USERNAME' in os.environ and 'PASSWORD' in os.environ:
        LI_AT_COOKIE = get_cookie(os.environ['USERNAME'], os.environ['PASSWORD'])
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
