"""Command line entry point: parse, build, dispatch."""

from __future__ import annotations

import logging
import os
import sys

from ..config import Config
from ..exceptions import ChromedriverResolutionException, InvalidCookieException
from ..linkedin_scraper import LinkedinScraper
from ..login import LOGIN_TIMEOUT, print_credentials, sign_in
from ..utils.session_source import display_path, resolve_login_profile
from .args import CliConfig, parse_args
from .color import Colorizer, color_enabled
from .events import Feedback, create_feedback, register_events
from .mapping import build_query, build_scraper_kwargs
from .output import OutputConfigError, Writer, create_writer
from .spinner import Spinner, create_spinner

# The conventional status for a command stopped by Ctrl-C, 128 + SIGINT
EXIT_INTERRUPTED = 130


_LOG_LEVELS = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARN': logging.WARNING,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'FATAL': logging.FATAL,
}


def _log_level(verbose: int) -> int:
    """The level the library logger runs at: LOG_LEVEL when it names one, else -v / -vv."""
    explicit = _LOG_LEVELS.get(os.environ.get('LOG_LEVEL', '').upper().strip())
    if explicit is not None:
        return explicit
    if verbose >= 2:
        return logging.DEBUG
    if verbose == 1:
        return logging.INFO
    return logging.WARNING


def _configure_logger(verbose: int) -> logging.Handler:
    """Route the library logger to stderr at the level -v / -vv / LOG_LEVEL ask for.

    The handler belongs to the CLI, never to the library, and does not propagate, so a
    record is printed once. The caller removes it with `_release_logger` when done.
    """
    library_logger = logging.getLogger(Config.LOGGER_NAMESPACE)
    level = _log_level(verbose)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter('%(levelname)s %(name)s: %(message)s'))
    library_logger.setLevel(level)
    library_logger.addHandler(handler)
    library_logger.propagate = False
    return handler


def _release_logger(handler: logging.Handler) -> None:
    library_logger = logging.getLogger(Config.LOGGER_NAMESPACE)
    library_logger.removeHandler(handler)
    library_logger.propagate = True


def _run_login(config: CliConfig) -> int:
    colorizer = Colorizer(color_enabled(config.no_color, sys.stdout))

    profile = resolve_login_profile(config.chrome_user_data_dir)

    print(f'Chrome profile: {display_path(profile)}')
    print(colorizer.dim('A browser window will open. Sign in there, ticking "Keep me logged in".'))
    print(colorizer.dim(f'Waiting up to {LOGIN_TIMEOUT}s for the session to be established...'))

    try:
        credentials = sign_in(
            profile,
            config.chrome_executable_path,
            config.chrome_binary_location,
        )
    except ChromedriverResolutionException as error:
        print(f'error: {error}', file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print(file=sys.stderr)
        print('Interrupted: no session was established.', file=sys.stderr, flush=True)
        return EXIT_INTERRUPTED

    if credentials is None:
        print(
            '❌ '
            + colorizer.red(
                'No session was established: timed out, or the browser was closed. '
                'The profile is unchanged.'
            )
        )
        return 1

    print_credentials(profile, credentials, colorizer)
    return 0


def _dispatch(config: CliConfig, writer: Writer, feedback: Feedback, spinner: Spinner) -> None:
    """Build the scraper, register handlers, and run the requested subcommand.

    Exceptions propagate to main(), which maps them onto exit codes; the writer is
    always closed and the spinner always stopped here whatever the outcome.
    """
    scraper = LinkedinScraper(**build_scraper_kwargs(config))
    register_events(scraper, writer, feedback)
    feedback.announce(config, scraper.session_source.summary())
    writer.begin()
    try:
        if config.subcommand == 'jobs':
            spinner.start('starting…')
            scraper.run(build_query(config))
        else:
            spinner.start('loading job…')
            scraper.scrape_job(config.url_or_id, apply_link=config.apply_link)
    finally:
        writer.end()
        spinner.stop()


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
    handler = _configure_logger(config.verbose)
    try:
        return _run(config)
    finally:
        _release_logger(handler)


def _run(config: CliConfig) -> int:
    if config.subcommand == 'login':
        return _run_login(config)

    spinner = create_spinner(config)

    try:
        writer = create_writer(config, spinner)
    except OutputConfigError as error:
        print(f'error: {error}', file=sys.stderr, flush=True)
        return 2

    feedback = create_feedback(config, spinner)

    raised_invalid_cookie = False
    raised_other = False
    other_message: str | None = None
    try:
        _dispatch(config, writer, feedback, spinner)
    except InvalidCookieException as error:
        raised_invalid_cookie = True
        feedback.report_invalid_session(str(error))
    # ruff: ignore[BLE001] whatever else a run raises, CallbackException included, is exit code 1
    except Exception as error:
        raised_other = True
        other_message = str(error)

    if feedback.invalid_session and not raised_invalid_cookie:
        feedback.report_invalid_session()

    if raised_other and not (
        raised_invalid_cookie or feedback.invalid_session or feedback.not_found
    ):
        print(f'error: {other_message}', file=sys.stderr, flush=True)

    return compute_exit_code(
        raised_invalid_cookie, feedback.invalid_session, feedback.not_found, raised_other
    )
