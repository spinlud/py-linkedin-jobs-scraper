import os
import logging
import urllib3
from ..config import Config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

max_length = 1000
logger = logging.getLogger(Config.LOGGER_NAMESPACE)
logger.setLevel(Config.LOGGER_LEVEL)


def __format(*args: object) -> str:
    """Join the arguments with tabs, truncating each one longer than `max_length` chars."""
    parts: list[str] = []
    for arg in args:
        text = str(arg)
        parts.append(text if len(text) <= max_length else f'{text[:max_length]}...')
    return '\t'.join(parts)


# The message is passed preformatted, never as `msg, *args`, so a `%` in it is printed as is.
# `stacklevel=2` attributes each record (funcName, lineno, pathname) to the helper's caller.

def debug(*args: object) -> None:
    logger.debug(__format(*args), stacklevel=2)


def info(*args: object) -> None:
    logger.info(__format(*args), stacklevel=2)


def warn(*args: object) -> None:
    logger.warning(__format(*args), stacklevel=2)


def error(*args: object, exc_info: bool = True) -> None:
    logger.error(__format(*args), exc_info=exc_info, stacklevel=2)
