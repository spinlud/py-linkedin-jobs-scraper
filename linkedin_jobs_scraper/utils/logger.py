import logging

logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(message)s',
    level=logging.INFO,
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
