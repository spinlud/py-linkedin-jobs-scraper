"""Offline tests for LinkedinScraper.__build_search_url query serialization.

Pure URL building: no network, no browser, no credentials. The method is a
staticmethod, reached through its name-mangled attribute.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from linkedin_jobs_scraper.linkedin_scraper import LinkedinScraper
from linkedin_jobs_scraper.exceptions import UnresolvedLocationError
import linkedin_jobs_scraper.filters as filters_module
from linkedin_jobs_scraper.query import Location, Query, QueryOptions, QueryFilters
from linkedin_jobs_scraper.filters import (
    TimeFilters,
    TypeFilters,
    ExperienceLevelFilters,
    OnSiteOrRemoteFilters,
)

_build_search_url = LinkedinScraper._LinkedinScraper__build_search_url


def _params(query: Query) -> dict[str, list[str]]:
    return parse_qs(urlparse(_build_search_url(query)).query, keep_blank_values=True)


def _query_with_filters(filters: QueryFilters) -> Query:
    return Query(query='engineer', options=QueryOptions(filters=filters))


# --- f_SAL --------------------------------------------------------------------

@pytest.mark.parametrize('member, expected', [
    (OnSiteOrRemoteFilters.ON_SITE, 'f_SA_id_225001:296001'),
    (OnSiteOrRemoteFilters.REMOTE, 'f_SA_id_225001:272001'),
    (OnSiteOrRemoteFilters.HYBRID, 'f_SA_id_225001:1621001'),
])
def test_workplace_section(member: OnSiteOrRemoteFilters, expected: str) -> None:
    assert _params(_query_with_filters(QueryFilters(on_site_or_remote=member)))['f_SAL'] == [expected]


@pytest.mark.parametrize('member, expected', [
    (ExperienceLevelFilters.ENTRY_LEVEL, 'f_SA_id_227001:276001'),
    (ExperienceLevelFilters.SENIOR, 'f_SA_id_227001:277001'),
    (ExperienceLevelFilters.MANAGER, 'f_SA_id_227001:278001'),
    (ExperienceLevelFilters.DIRECTOR, 'f_SA_id_227001:272003'),
    (ExperienceLevelFilters.EXECUTIVE, 'f_SA_id_227001:279001'),
])
def test_experience_section(member: ExperienceLevelFilters, expected: str) -> None:
    assert _params(_query_with_filters(QueryFilters(experience=member)))['f_SAL'] == [expected]


@pytest.mark.parametrize('member, expected', [
    (TypeFilters.FULL_TIME, 'f_SA_id_226001:272015'),
    (TypeFilters.PART_TIME, 'f_SA_id_226001:273001'),
    (TypeFilters.CONTRACT, 'f_SA_id_226001:274001'),
    (TypeFilters.INTERNSHIP, 'f_SA_id_226001:275001'),
    (TypeFilters.VOLUNTEER, 'f_SA_id_226001:272002'),
])
def test_employment_type_section(member: TypeFilters, expected: str) -> None:
    assert _params(_query_with_filters(QueryFilters(type=member)))['f_SAL'] == [expected]


def test_several_values_in_one_section_are_comma_separated() -> None:
    params = _params(_query_with_filters(QueryFilters(
        on_site_or_remote=[OnSiteOrRemoteFilters.REMOTE, OnSiteOrRemoteFilters.HYBRID])))
    assert params['f_SAL'] == ['f_SA_id_225001:272001,1621001']


def test_sections_are_joined_with_dollar_in_a_stable_order() -> None:
    expected = ['f_SA_id_225001:1621001$f_SA_id_227001:277001,278001$f_SA_id_226001:272015']
    params = _params(_query_with_filters(QueryFilters(
        type=TypeFilters.FULL_TIME,
        experience=[ExperienceLevelFilters.SENIOR, ExperienceLevelFilters.MANAGER],
        on_site_or_remote=OnSiteOrRemoteFilters.HYBRID,
    )))
    assert params['f_SAL'] == expected


def test_no_section_emits_no_f_sal() -> None:
    assert 'f_SAL' not in _params(_query_with_filters(QueryFilters(easy_apply=True)))


@pytest.mark.parametrize('param', ['f_JT', 'f_E', 'f_WT'])
def test_old_section_params_are_never_emitted(param: str) -> None:
    params = _params(_query_with_filters(QueryFilters(
        type=TypeFilters.CONTRACT,
        experience=ExperienceLevelFilters.SENIOR,
        on_site_or_remote=OnSiteOrRemoteFilters.REMOTE,
    )))
    assert param not in params


# --- toggles and kept filters -----------------------------------------------

def test_verified_toggle() -> None:
    assert _params(_query_with_filters(QueryFilters(verified=True)))['f_VJ'] == ['true']
    assert 'f_VJ' not in _params(_query_with_filters(QueryFilters(verified=False)))


def test_easy_apply_toggle() -> None:
    on = _params(_query_with_filters(QueryFilters(easy_apply=True)))
    assert on['f_AL'] == ['true']

    off = _params(_query_with_filters(QueryFilters(easy_apply=False)))
    assert 'f_AL' not in off


def test_under_10_applicants_toggle() -> None:
    on = _params(_query_with_filters(QueryFilters(under_10_applicants=True)))
    assert on['f_EA'] == ['true']

    off = _params(_query_with_filters(QueryFilters(under_10_applicants=False)))
    assert 'f_EA' not in off


def test_time_filter() -> None:
    assert _params(_query_with_filters(QueryFilters(time=TimeFilters.WEEK)))['f_TPR'] == ['r604800']


def test_company_jobs_url_is_reduced_to_its_f_c() -> None:
    url = 'https://www.linkedin.com/jobs/search/?f_C=1441%2C17876832&geoId=92000000'
    assert _params(_query_with_filters(QueryFilters(company_jobs_url=url)))['f_C'] == ['1441,17876832']


def test_company_id_is_used_as_f_c() -> None:
    assert _params(_query_with_filters(QueryFilters(company_id='1441')))['f_C'] == ['1441']


# --- removed filters ----------------------------------------------------------

@pytest.mark.parametrize('name', [
    'RelevanceFilters', 'SalaryBaseFilters', 'IndustryFilters',
    'JobFunctionFilters', 'BenefitsFilters', 'CommitmentsFilters',
])
def test_removed_filter_enums_no_longer_exist(name: str) -> None:
    assert not hasattr(filters_module, name)


@pytest.mark.parametrize('kwarg', [
    'relevance', 'base_salary', 'industry', 'job_function', 'benefits', 'commitments',
])
def test_removed_filter_arguments_are_refused(kwarg: str) -> None:
    with pytest.raises(TypeError):
        QueryFilters(**{kwarg: 'x'})


@pytest.mark.parametrize('param', ['sortBy', 'f_SB2', 'f_I', 'f_F', 'f_BE', 'f_JC'])
def test_removed_params_are_never_emitted(param: str) -> None:
    params = _params(_query_with_filters(QueryFilters(
        time=TimeFilters.DAY, type=TypeFilters.FULL_TIME, easy_apply=True,
        under_10_applicants=True, verified=True, company_id='1')))
    assert param not in params


# --- location ---------------------------------------------------------------

WORLDWIDE_GEO_ID = '92000000'


def _location_params(location: object = '') -> dict[str, list[str]]:
    url = _build_search_url(Query(query='engineer'), location)
    return parse_qs(urlparse(url).query, keep_blank_values=True)


def test_url_targets_the_search_results_route() -> None:
    url = urlparse(_build_search_url(Query(query='engineer'), 'Worldwide'))
    assert (url.netloc, url.path) == ('www.linkedin.com', '/jobs/search-results/')


def test_no_location_means_worldwide() -> None:
    assert _location_params()['geoId'] == [WORLDWIDE_GEO_ID]


def test_worldwide_name_means_worldwide() -> None:
    assert _location_params('Worldwide')['geoId'] == [WORLDWIDE_GEO_ID]


def test_location_object_is_used_as_is() -> None:
    assert _location_params(Location(geo_id='103350119', name='Italy'))['geoId'] == ['103350119']


def test_numeric_string_is_a_geo_id() -> None:
    assert _location_params('105080838')['geoId'] == ['105080838']


@pytest.mark.parametrize('location', ['', 'Worldwide', '105080838', Location(geo_id='1')])
def test_location_param_is_never_emitted(location: object) -> None:
    assert 'location' not in _location_params(location)


def test_start_is_always_set() -> None:
    assert _location_params()['start'] == ['0']


def test_unresolved_location_name_is_refused() -> None:
    with pytest.raises(UnresolvedLocationError):
        _build_search_url(Query(query='engineer'), 'Germany')
