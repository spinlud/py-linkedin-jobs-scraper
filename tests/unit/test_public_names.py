import pytest

PUBLIC_NAMES = {
    'linkedin_jobs_scraper': {'LinkedinScraper'},
    'linkedin_jobs_scraper.events': {
        'EventBegin',
        'EventData',
        'EventMetrics',
        'EventNotFound',
        'EventSession',
        'Events',
    },
    'linkedin_jobs_scraper.exceptions': {
        'CallbackException',
        'ChromedriverResolutionException',
        'InvalidCookieException',
        'LocationResolutionError',
        'UnresolvedLocationError',
    },
    'linkedin_jobs_scraper.filters': {
        'EMPLOYMENT_TYPE_FACET',
        'EXPERIENCE_FACET',
        'ExperienceLevelFilters',
        'OnSiteOrRemoteFilters',
        'TimeFilters',
        'TypeFilters',
        'WORKPLACE_FACET',
    },
    'linkedin_jobs_scraper.query': {'Location', 'Query', 'QueryFilters', 'QueryOptions'},
}


@pytest.mark.parametrize('package, names', PUBLIC_NAMES.items())
def test_a_star_import_gives_the_public_names_and_no_submodule(
    package: str, names: set[str]
) -> None:
    namespace: dict[str, object] = {}
    exec(f'from {package} import *', namespace)

    assert set(namespace) - {'__builtins__'} == names
