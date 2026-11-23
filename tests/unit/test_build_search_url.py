"""Offline tests for LinkedinScraper.__build_search_url query serialization.

Pure URL building: no network, no browser, no credentials. The method is a
staticmethod, reached through its name-mangled attribute.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from linkedin_jobs_scraper.linkedin_scraper import LinkedinScraper
from linkedin_jobs_scraper.exceptions import UnresolvedLocationError
from linkedin_jobs_scraper.query import Location, Query, QueryOptions, QueryFilters
from linkedin_jobs_scraper.filters import (
    TypeFilters,
    OnSiteOrRemoteFilters,
    JobFunctionFilters,
    BenefitsFilters,
    CommitmentsFilters,
)

_build_search_url = LinkedinScraper._LinkedinScraper__build_search_url


def _params(query: Query) -> dict[str, list[str]]:
    return parse_qs(urlparse(_build_search_url(query)).query, keep_blank_values=True)


def _query_with_filters(filters: QueryFilters) -> Query:
    return Query(query='engineer', options=QueryOptions(filters=filters))


def test_job_function_single_and_multi_serialize() -> None:
    single = _params(_query_with_filters(
        QueryFilters(job_function=JobFunctionFilters.ENGINEERING)))
    assert single['f_F'] == ['eng']

    multi = _params(_query_with_filters(QueryFilters(
        job_function=[JobFunctionFilters.ENGINEERING, JobFunctionFilters.SALES])))
    assert multi['f_F'] == ['eng,sale']


def test_benefits_single_and_multi_serialize() -> None:
    single = _params(_query_with_filters(QueryFilters(benefits=BenefitsFilters.MEDICAL)))
    assert single['f_BE'] == ['1']

    multi = _params(_query_with_filters(QueryFilters(
        benefits=[BenefitsFilters.MEDICAL, BenefitsFilters.DISABILITY_INSURANCE])))
    assert multi['f_BE'] == ['1,12']


def test_commitments_single_and_multi_serialize() -> None:
    single = _params(_query_with_filters(
        QueryFilters(commitments=CommitmentsFilters.WORK_LIFE_BALANCE)))
    assert single['f_JC'] == ['3']

    multi = _params(_query_with_filters(QueryFilters(commitments=[
        CommitmentsFilters.DIVERSITY_EQUITY_INCLUSION,
        CommitmentsFilters.SOCIAL_IMPACT,
    ])))
    assert multi['f_JC'] == ['1,4']


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


def test_on_site_or_remote_absent_emits_no_f_wt() -> None:
    # Regression: an unset on_site_or_remote must not append an empty f_WT param.
    params = _params(_query_with_filters(QueryFilters(type=TypeFilters.FULL_TIME)))
    assert 'f_JT' in params
    assert 'f_WT' not in params


def test_on_site_or_remote_set_still_serializes() -> None:
    params = _params(_query_with_filters(
        QueryFilters(on_site_or_remote=OnSiteOrRemoteFilters.REMOTE)))
    assert params['f_WT'] == ['2']


def test_kitchen_sink_all_new_filters() -> None:
    params = _params(_query_with_filters(QueryFilters(
        type=[TypeFilters.FULL_TIME, TypeFilters.CONTRACT],
        on_site_or_remote=OnSiteOrRemoteFilters.REMOTE,
        job_function=[JobFunctionFilters.ENGINEERING, JobFunctionFilters.INFORMATION_TECHNOLOGY],
        benefits=[BenefitsFilters.MEDICAL, BenefitsFilters.VISION],
        commitments=[CommitmentsFilters.WORK_LIFE_BALANCE],
        easy_apply=True,
        under_10_applicants=True,
    )))

    assert params['f_JT'] == ['F,C']
    assert params['f_WT'] == ['2']
    assert params['f_F'] == ['eng,it']
    assert params['f_BE'] == ['1,2']
    assert params['f_JC'] == ['3']
    assert params['f_AL'] == ['true']
    assert params['f_EA'] == ['true']


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


def test_unresolved_location_name_is_refused() -> None:
    with pytest.raises(UnresolvedLocationError):
        _build_search_url(Query(query='engineer'), 'Germany')


def test_start_is_always_set() -> None:
    assert _location_params()['start'] == ['0']
