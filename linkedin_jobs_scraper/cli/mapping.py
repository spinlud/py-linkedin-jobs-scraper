"""Pure translation from parsed CLI config into scraper domain objects.

No I/O and no browser here: every function takes a CliConfig and returns plain
domain values, so the mapping can be exercised without launching Chrome.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, TYPE_CHECKING

from ..filters import (
    RelevanceFilters,
    TimeFilters,
    TypeFilters,
    ExperienceLevelFilters,
    OnSiteOrRemoteFilters,
    IndustryFilters,
    SalaryBaseFilters,
)
from ..query import Query, QueryOptions, QueryFilters, Location

if TYPE_CHECKING:
    from .args import CliConfig


def _member_to_kebab(name: str, strip_prefix: str = '') -> str:
    """Convert an enum member name into its kebab-case CLI token."""
    if strip_prefix and name.startswith(strip_prefix):
        name = name[len(strip_prefix):]
    return name.lower().replace('_', '-')


def _kebab_map(enum_cls: type[Enum], strip_prefix: str = '') -> dict[str, Enum]:
    """Build a {kebab token: enum member} map generically from an enum class."""
    return {_member_to_kebab(member.name, strip_prefix): member for member in enum_cls}


# Derived from the enum members so the CLI tokens cannot drift from the enums.
RELEVANCE_CHOICES = _kebab_map(RelevanceFilters)
TIME_CHOICES = _kebab_map(TimeFilters)
SALARY_CHOICES = _kebab_map(SalaryBaseFilters, strip_prefix='SALARY_')
TYPE_CHOICES = _kebab_map(TypeFilters)
EXPERIENCE_CHOICES = _kebab_map(ExperienceLevelFilters)
WORKPLACE_CHOICES = _kebab_map(OnSiteOrRemoteFilters)
INDUSTRY_CHOICES = _kebab_map(IndustryFilters)


def build_scraper_kwargs(config: CliConfig) -> dict[str, Any]:
    """Map driver flags onto LinkedinScraper.__init__ keyword arguments."""
    return {
        'headless': not config.no_headless,
        'slow_mo': config.slow_mo,
        'adaptive_slow_mo': not config.no_adaptive_slow_mo,
        'page_load_timeout': config.page_load_timeout,
        'chrome_executable_path': config.chrome_executable_path,
        'chrome_binary_location': config.chrome_binary_location,
        'chrome_user_data_dir': config.chrome_user_data_dir,
        'interactive_login': config.interactive_login,
    }


def build_locations(config: CliConfig) -> list[str | Location] | None:
    """Map --location to plain strings and --geo-id to Location objects.

    The two are mutually exclusive at the parser, so at most one list is populated.
    Returns None when neither is given, letting the scraper apply its own default.
    """
    locations: list[str | Location] = list(config.location)
    locations += [Location(geo_id=str(geo_id)) for geo_id in config.geo_id]
    return locations or None


def describe_locations(config: CliConfig) -> list[str]:
    """Human-readable location labels in the same order build_locations produces them.

    Each --location string appears as-is, then each --geo-id as 'geoId:<id>'. When neither
    is given the scraper defaults to Worldwide, so a single 'Worldwide' label is returned.
    """
    labels = list(config.location)
    labels += [f'geoId:{geo_id}' for geo_id in config.geo_id]
    return labels or ['Worldwide']


def build_query_filters(config: CliConfig) -> QueryFilters | None:
    """Build QueryFilters from only the filters the user actually provided."""
    kwargs: dict[str, Any] = {}

    if config.company_jobs_url is not None:
        kwargs['company_jobs_url'] = config.company_jobs_url
    if config.relevance is not None:
        kwargs['relevance'] = RELEVANCE_CHOICES[config.relevance]
    if config.time is not None:
        kwargs['time'] = TIME_CHOICES[config.time]
    if config.salary is not None:
        kwargs['base_salary'] = SALARY_CHOICES[config.salary]
    if config.type:
        kwargs['type'] = [TYPE_CHOICES[token] for token in config.type]
    if config.experience:
        kwargs['experience'] = [EXPERIENCE_CHOICES[token] for token in config.experience]
    if config.workplace:
        kwargs['on_site_or_remote'] = [WORKPLACE_CHOICES[token] for token in config.workplace]
    if config.industry:
        kwargs['industry'] = [INDUSTRY_CHOICES[token] for token in config.industry]

    if not kwargs:
        return None
    return QueryFilters(**kwargs)


def build_query_options(config: CliConfig) -> QueryOptions:
    """Assemble QueryOptions from the search options and filters."""
    return QueryOptions(
        limit=config.limit,
        locations=build_locations(config),
        filters=build_query_filters(config),
        apply_link=config.apply_link,
        skip_promoted_jobs=config.skip_promoted_jobs,
        page_offset=config.page_offset,
    )


def build_query(config: CliConfig) -> Query:
    """Build a Query for the jobs subcommand."""
    return Query(query=config.query, options=build_query_options(config))
