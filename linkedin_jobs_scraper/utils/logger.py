import os
import logging
import urllib3
from ..config import Config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

max_length = 1000
logger = logging.getLogger(Config.LOGGER_NAMESPACE)
logger.setLevel(Config.LOGGER_LEVEL)


def __format(*args):
    return '\t'.join([str(arg) if len(str(args)) <= max_length else f'{str(arg)[:max_length]}...' for arg in args])


def debug(*args):
    logger.debug(__format(args))


def info(*args):
    logger.info(__format(args))


def warn(*args):
    logger.warning(__format(args))


def error(*args):
    logger.error(__format(args), exc_info=True)
