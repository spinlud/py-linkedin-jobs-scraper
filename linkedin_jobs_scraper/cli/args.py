"""Argument parsing for the linkedin_jobs_scraper command line interface.

Builds the argparse parser and reduces the parsed namespace into a typed CliConfig
dataclass the rest of the CLI consumes.
"""
from __future__ import annotations

import argparse
import importlib.metadata
from dataclasses import dataclass, field

from .mapping import (
    RELEVANCE_CHOICES,
    TIME_CHOICES,
    SALARY_CHOICES,
    TYPE_CHOICES,
    EXPERIENCE_CHOICES,
    WORKPLACE_CHOICES,
    INDUSTRY_CHOICES,
)

PACKAGE_DISTRIBUTION_NAME = 'linkedin-jobs-scraper'

DEFAULT_SLOW_MO = 0.8
DEFAULT_PAGE_LOAD_TIMEOUT = 20
DEFAULT_LIMIT = 25
DEFAULT_PAGE_OFFSET = 0

OUTPUT_FORMATS = ('table', 'jsonl', 'json', 'csv')


@dataclass
class CliConfig:
    """Typed view of the parsed command line, one flat record for every subcommand."""

    subcommand: str

    # Global
    quiet: bool = False
    verbose: int = 0
    no_color: bool = False

    # Driver
    no_headless: bool = False
    slow_mo: float = DEFAULT_SLOW_MO
    no_adaptive_slow_mo: bool = False
    page_load_timeout: int = DEFAULT_PAGE_LOAD_TIMEOUT
    chrome_executable_path: str | None = None
    chrome_binary_location: str | None = None
    chrome_user_data_dir: str | None = None
    interactive_login: bool = False

    # Output
    out_format: str | None = None
    out_path: str | None = None
    fields: list[str] | None = None
    all_fields: bool = False
    vertical: bool = False
    raw: bool = False

    # search
    query: str = ''
    location: list[str] = field(default_factory=list)
    geo_id: list[str] = field(default_factory=list)
    limit: int = DEFAULT_LIMIT
    apply_link: bool = False
    skip_promoted_jobs: bool = False
    page_offset: int = DEFAULT_PAGE_OFFSET
    relevance: str | None = None
    time: str | None = None
    salary: str | None = None
    company_jobs_url: str | None = None
    type: list[str] = field(default_factory=list)
    experience: list[str] = field(default_factory=list)
    workplace: list[str] = field(default_factory=list)
    industry: list[str] = field(default_factory=list)

    # scrape-job
    url_or_id: str = ''


def _package_version() -> str:
    """Read the version from the installed distribution metadata, the single source."""
    try:
        return importlib.metadata.version(PACKAGE_DISTRIBUTION_NAME)
    except importlib.metadata.PackageNotFoundError:
        return 'unknown'


def _comma_separated_choice_action(allowed: dict[str, object]) -> type[argparse.Action]:
    """Build an append action that also splits comma-separated tokens in one option.

    Each token is validated against the allowed kebab keys so `--type full-time,contract`
    and `--type full-time --type contract` both work and both reject unknown values.
    """

    class _Action(argparse.Action):
        def __call__(self, parser, namespace, values, option_string=None):  # type: ignore[override]
            items: list[str] = list(getattr(namespace, self.dest) or [])
            for raw_token in str(values).split(','):
                token = raw_token.strip()
                if not token:
                    continue
                if token not in allowed:
                    choices = ', '.join(allowed)
                    parser.error(
                        f"argument {option_string}: invalid choice: '{token}' (choose from {choices})")
                items.append(token)
            setattr(namespace, self.dest, items)

    return _Action


def _add_driver_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group('driver')
    group.add_argument('--no-headless', action='store_true',
                       help='Run Chrome with a visible window')
    group.add_argument('--slow-mo', type=float, default=DEFAULT_SLOW_MO,
                       help='Floor on seconds slept between jobs (default: %(default)s)')
    group.add_argument('--no-adaptive-slow-mo', action='store_true',
                       help='Keep slow-mo a fixed delay instead of adapting to 429s')
    group.add_argument('--page-load-timeout', type=int, default=DEFAULT_PAGE_LOAD_TIMEOUT,
                       help='Page load timeout in seconds (default: %(default)s)')
    group.add_argument('--chrome-executable-path', default=None, help='Path to chromedriver')
    group.add_argument('--chrome-binary-location', default=None, help='Path to the Chrome binary')
    group.add_argument('--chrome-user-data-dir', default=None,
                       help='Chrome profile directory kept across runs')
    group.add_argument('--interactive-login', action='store_true',
                       help='Sign in by hand into the profile before scraping')


def _add_output_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group('output')
    group.add_argument('-f', '--out-format', choices=OUTPUT_FORMATS, default=None,
                       help='Output format (resolved from the destination when omitted)')
    group.add_argument('-o', '--out-path', default=None,
                       help="Output destination; '-' means stdout")
    group.add_argument('--fields', default=None,
                       help='Comma-separated list of fields to emit')
    group.add_argument('--all-fields', action='store_true', help='Emit every available field')
    group.add_argument('--vertical', action='store_true', help='Render one field per line')
    group.add_argument('--raw', action='store_true', help='Emit the raw record unformatted')


def _add_search_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('query', nargs='?', default='', help='Search keywords')

    locations = parser.add_mutually_exclusive_group()
    locations.add_argument('--location', action='append', default=None, metavar='LOCATION',
                           help='Location name (repeatable). Mutually exclusive with --geo-id')
    locations.add_argument('--geo-id', action='append', default=None, metavar='GEO_ID',
                           help='LinkedIn geoId (repeatable). Mutually exclusive with --location')

    options = parser.add_argument_group('options')
    options.add_argument('--limit', type=int, default=DEFAULT_LIMIT,
                         help='Maximum jobs to scrape, 0 for unlimited (default: %(default)s)')
    options.add_argument('--apply-link', action='store_true',
                         help='Resolve the external apply link for each job')
    options.add_argument('--skip-promoted-jobs', action='store_true', help='Skip promoted jobs')
    options.add_argument('--page-offset', type=int, default=DEFAULT_PAGE_OFFSET,
                         help='Number of result pages to skip (default: %(default)s)')

    filters = parser.add_argument_group('filters')
    filters.add_argument('--relevance', choices=list(RELEVANCE_CHOICES), default=None,
                         help='Sort order')
    filters.add_argument('--time', choices=list(TIME_CHOICES), default=None,
                         help='Time posted')
    filters.add_argument('--salary', choices=list(SALARY_CHOICES), default=None,
                         help='Minimum base salary')
    filters.add_argument('--company-jobs-url', default=None,
                         help='LinkedIn company jobs url to extract the company filter from')
    filters.add_argument('--type', action=_comma_separated_choice_action(TYPE_CHOICES),
                         default=None, metavar='TYPE',
                         help=f'Job type, repeatable or comma-separated: {", ".join(TYPE_CHOICES)}')
    filters.add_argument('--experience', action=_comma_separated_choice_action(EXPERIENCE_CHOICES),
                         default=None, metavar='EXPERIENCE',
                         help=f'Experience level, repeatable or comma-separated: {", ".join(EXPERIENCE_CHOICES)}')
    filters.add_argument('--workplace', action=_comma_separated_choice_action(WORKPLACE_CHOICES),
                         default=None, metavar='WORKPLACE',
                         help=f'On-site/remote, repeatable or comma-separated: {", ".join(WORKPLACE_CHOICES)}')
    filters.add_argument('--industry', action=_comma_separated_choice_action(INDUSTRY_CHOICES),
                         default=None, metavar='INDUSTRY',
                         help=f'Industry, repeatable or comma-separated: {", ".join(INDUSTRY_CHOICES)}')


def _add_scrape_job_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('url_or_id', help="A job id or a '/jobs/view/<id>' url")
    parser.add_argument('--apply-link', action='store_true',
                        help='Resolve the external apply link for the job')


def _add_login_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--chrome-user-data-dir', required=True,
                        help='Chrome profile directory to create or reuse')
    parser.add_argument('--chrome-executable-path', default=None, help='Path to chromedriver')
    parser.add_argument('--chrome-binary-location', default=None, help='Path to the Chrome binary')


def build_parser() -> argparse.ArgumentParser:
    """Build the full argparse parser with all subcommands and flags."""
    parser = argparse.ArgumentParser(
        description='Scrape public LinkedIn job postings from the command line.')

    parser.add_argument('--quiet', action='store_true', help='Suppress non-error output')
    parser.add_argument('-v', '--verbose', action='count', default=0,
                        help='Increase verbosity (repeatable)')
    parser.add_argument('--no-color', action='store_true', help='Disable coloured output')
    parser.add_argument('--version', action='version',
                        version=f'%(prog)s {_package_version()}')

    subparsers = parser.add_subparsers(dest='subcommand', required=True)

    search = subparsers.add_parser('search', help='Search and scrape jobs')
    _add_driver_arguments(search)
    _add_output_arguments(search)
    _add_search_arguments(search)

    scrape_job = subparsers.add_parser('scrape-job', help='Scrape a single job by url or id')
    _add_driver_arguments(scrape_job)
    _add_output_arguments(scrape_job)
    _add_scrape_job_arguments(scrape_job)

    login = subparsers.add_parser('login', help='Sign in once into a reusable Chrome profile')
    _add_login_arguments(login)

    return parser


def _namespace_to_config(namespace: argparse.Namespace) -> CliConfig:
    """Reduce the parsed namespace into a CliConfig, filling absent attrs with defaults."""
    raw_fields = getattr(namespace, 'fields', None)
    fields = None
    if raw_fields:
        fields = [name.strip() for name in raw_fields.split(',') if name.strip()]

    return CliConfig(
        subcommand=namespace.subcommand,
        quiet=getattr(namespace, 'quiet', False),
        verbose=getattr(namespace, 'verbose', 0),
        no_color=getattr(namespace, 'no_color', False),
        no_headless=getattr(namespace, 'no_headless', False),
        slow_mo=getattr(namespace, 'slow_mo', DEFAULT_SLOW_MO),
        no_adaptive_slow_mo=getattr(namespace, 'no_adaptive_slow_mo', False),
        page_load_timeout=getattr(namespace, 'page_load_timeout', DEFAULT_PAGE_LOAD_TIMEOUT),
        chrome_executable_path=getattr(namespace, 'chrome_executable_path', None),
        chrome_binary_location=getattr(namespace, 'chrome_binary_location', None),
        chrome_user_data_dir=getattr(namespace, 'chrome_user_data_dir', None),
        interactive_login=getattr(namespace, 'interactive_login', False),
        out_format=getattr(namespace, 'out_format', None),
        out_path=getattr(namespace, 'out_path', None),
        fields=fields,
        all_fields=getattr(namespace, 'all_fields', False),
        vertical=getattr(namespace, 'vertical', False),
        raw=getattr(namespace, 'raw', False),
        query=getattr(namespace, 'query', ''),
        location=list(getattr(namespace, 'location', None) or []),
        geo_id=list(getattr(namespace, 'geo_id', None) or []),
        limit=getattr(namespace, 'limit', DEFAULT_LIMIT),
        apply_link=getattr(namespace, 'apply_link', False),
        skip_promoted_jobs=getattr(namespace, 'skip_promoted_jobs', False),
        page_offset=getattr(namespace, 'page_offset', DEFAULT_PAGE_OFFSET),
        relevance=getattr(namespace, 'relevance', None),
        time=getattr(namespace, 'time', None),
        salary=getattr(namespace, 'salary', None),
        company_jobs_url=getattr(namespace, 'company_jobs_url', None),
        type=list(getattr(namespace, 'type', None) or []),
        experience=list(getattr(namespace, 'experience', None) or []),
        workplace=list(getattr(namespace, 'workplace', None) or []),
        industry=list(getattr(namespace, 'industry', None) or []),
        url_or_id=getattr(namespace, 'url_or_id', ''),
    )


def parse_args(argv: list[str] | None = None) -> CliConfig:
    """Parse argv into a typed CliConfig."""
    parser = build_parser()
    namespace = parser.parse_args(argv)
    return _namespace_to_config(namespace)
