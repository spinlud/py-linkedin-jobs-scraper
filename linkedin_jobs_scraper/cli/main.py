"""Command line entry point: parse, build, dispatch."""
from __future__ import annotations

import logging
import os
import sys

from ..config import Config
from ..exceptions import InvalidCookieException
from ..linkedin_scraper import LinkedinScraper
from ..login import LOGIN_TIMEOUT, print_credentials, sign_in
from .args import CliConfig, parse_args
from .events import Feedback, create_feedback, register_events
from .mapping import build_query, build_scraper_kwargs
from .output import OutputConfigError, Writer, create_writer


def _configure_logger(verbose: int) -> None:
    """Quiet the noisy library logger, unless LOG_LEVEL pins a level explicitly.

    Default is WARNING; -v raises it to INFO and -vv (or more) to DEBUG. An explicit
    LOG_LEVEL in the environment always wins and is left untouched.
    """
    if 'LOG_LEVEL' in os.environ:
        return

    if verbose >= 2:
        level = logging.DEBUG
    elif verbose == 1:
        level = logging.INFO
    else:
        level = logging.WARNING

    logging.getLogger(Config.LOGGER_NAMESPACE).setLevel(level)


def _run_login(config: CliConfig) -> int:
    print(f'Chrome profile: {config.chrome_user_data_dir}')
    print('A browser window will open. Sign in there, ticking "Keep me logged in".')
    print(f'Waiting up to {LOGIN_TIMEOUT}s for the session to be established...')

    credentials = sign_in(
        config.chrome_user_data_dir,
        config.chrome_executable_path,
        config.chrome_binary_location,
    )

    if credentials is None:
        print('Timed out: no session was established. The profile is unchanged.')
        return 1

    print_credentials(config.chrome_user_data_dir, credentials)
    return 0


def _dispatch(config: CliConfig, writer: Writer, feedback: Feedback) -> None:
    """Build the scraper, register handlers, and run the requested subcommand.

    Exceptions propagate to main(), which maps them onto exit codes; the writer is
    always closed here so its output is flushed whatever the outcome.
    """
    scraper = LinkedinScraper(**build_scraper_kwargs(config))
    register_events(scraper, writer, feedback)
    writer.begin()
    try:
        if config.subcommand == 'search':
            scraper.run(build_query(config))
        else:
            scraper.scrape_job(config.url_or_id, apply_link=config.apply_link)
    finally:
        writer.end()


def compute_exit_code(
    raised_invalid_cookie: bool,
    invalid_session: bool,
    not_found: bool,
    raised_other: bool,
) -> int:
    """Map the run outcomes onto an exit code.

    Precedence: a refused session outranks a missing job, which outranks any other error.
    """
    if raised_invalid_cookie or invalid_session:
        return 2
    if not_found:
        return 3
    if raised_other:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv)
    _configure_logger(config.verbose)

    if config.subcommand == 'login':
        return _run_login(config)

    try:
        writer = create_writer(config)
    except OutputConfigError as error:
        print(f'error: {error}', file=sys.stderr, flush=True)
        return 2

    feedback = create_feedback(config)

    raised_invalid_cookie = False
    raised_other = False
    other_message: str | None = None
    try:
        _dispatch(config, writer, feedback)
    except InvalidCookieException:
        raised_invalid_cookie = True
    except Exception as error:  # includes CallbackException
        raised_other = True
        other_message = str(error)

    if raised_other and not (raised_invalid_cookie or feedback.invalid_session or feedback.not_found):
        print(f'error: {other_message}', file=sys.stderr, flush=True)

    return compute_exit_code(
        raised_invalid_cookie, feedback.invalid_session, feedback.not_found, raised_other)
