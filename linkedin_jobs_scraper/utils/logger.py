import os
import logging
from ..config import Config

logger = logging.getLogger(Config.LOGGER_NAMESPACE)
logger.setLevel(Config.LOGGER_LEVEL)


def __format(*args):
    return '\t'.join([str(arg) for arg in args])


def debug(*args):
    logger.debug(__format(args))


def info(*args):
    logger.info(__format(args))


def warn(*args):
    logger.warning(__format(args))


def error(*args):
    logger.error(__format(args), exc_info=True)
