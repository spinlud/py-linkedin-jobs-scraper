"""Offline tests for the pure text helpers.

The applicant-clause extractor is pure, so every assertion is exact; no network or
browser is involved.
"""

from __future__ import annotations

import pytest

from linkedin_jobs_scraper.utils.text import clean_applicant_count


@pytest.mark.parametrize(
    'text, expected',
    [
        # Trailing badges are concatenated without a "·" separator and must be dropped
        ('Over 100 people clicked apply Promoted by hirer', 'Over 100 people clicked apply'),
        ('Over 100 applicants Promoted by hirer', 'Over 100 applicants'),
        ('1,234 applicants Actively reviewing applicants', '1,234 applicants'),
        # Clean clauses pass through unchanged
        ('27 applicants', '27 applicants'),
        ('1 applicant', '1 applicant'),
        ('50+ applicants', '50+ applicants'),
        ('200 people clicked apply', '200 people clicked apply'),
        # Nothing to extract
        ('New York, NY', ''),
        ('', ''),
        ('lorem ipsum dolor', ''),
    ],
)
def test_clean_applicant_count(text: str, expected: str) -> None:
    assert clean_applicant_count(text) == expected
