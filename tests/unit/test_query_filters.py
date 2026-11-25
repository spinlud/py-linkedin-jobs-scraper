"""What QueryFilters says about a company jobs url it refuses."""

from __future__ import annotations

import pytest

from linkedin_jobs_scraper.query import QueryFilters


def test_a_company_url_without_a_company_id_is_invalid() -> None:
    filters = QueryFilters(company_jobs_url='https://www.linkedin.com/jobs/search/?geoId=92000000')

    with pytest.raises(ValueError, match='Parameter company_jobs_url is invalid'):
        filters.validate()


@pytest.mark.parametrize('value', ['acme', 'http://[acme'])
def test_a_company_url_that_is_not_a_url_must_be_one(value: str) -> None:
    with pytest.raises(ValueError, match='Parameter company_jobs_url must be a valid url'):
        QueryFilters(company_jobs_url=value).validate()


def test_a_company_url_with_a_company_id_is_accepted() -> None:
    QueryFilters(company_jobs_url='https://www.linkedin.com/jobs/search/?f_C=1441').validate()
