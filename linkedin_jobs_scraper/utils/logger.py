import logging

logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(message)s',
    level=logging.DEBUG,
    datefmt='%Y-%m-%d %H:%M:%S')


def __format(*args):
    return '\t'.join([str(arg) for arg in args])


def debug(*args):
    logging.debug(__format(args))


def info(*args):
    logging.info(__format(args))


def warn(*args):
    logging.warning(__format(args))


def error(*args):
    logging.error(__format(args), exc_info=True)


def set_level(level):
    logging.getLogger().setLevel(level)


def set_level_debug(level):
    logging.getLogger().setLevel(logging.DEBUG)


def set_level_info():
    logging.getLogger().setLevel(logging.INFO)


def set_level_warn():
    logging.getLogger().setLevel(logging.WARN)


def set_level_error():
    logging.getLogger().setLevel(logging.ERROR)
