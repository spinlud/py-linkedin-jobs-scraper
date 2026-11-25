"""Offline tests for the raw page record -> EventData seam.

Every input is a string captured from LinkedIn's jobs search-results page.
"""

from __future__ import annotations

import pytest

from linkedin_jobs_scraper.utils.job_record import (
    RawJobRecord,
    parse_job_record,
    parse_results_total,
)

IMG = 'https://media.licdn.com/dms/image/v2/D4D0BAQGnw939z1kvYw/company-logo_100_100/x.png'

# A verified, promoted card showing a salary
VERIFIED_PROMOTED: RawJobRecord = {
    'job_id': '4438239210',
    'card_texts': [
        'Junior Software Engineer (Verified job)\nJunior Software Engineer ',
        'Lexroom',
        'Milan (Hybrid)',
        '30K EUR/yr - 50K EUR/yr',
        'Viewed',
        ' · ',
        'Promoted',
    ],
    'card_labels': ['More options', 'Dismiss Junior Software Engineer job'],
    'card_img': IMG,
}

# An Easy Apply card, promoted
EASY_APPLY_PROMOTED: RawJobRecord = {
    'job_id': '4492629290',
    'card_texts': [
        'Senior Full Stack Developer\nSenior Full Stack Developer',
        'CardTrader',
        'Padua (On-site)',
        'Actively reviewing applicants',
        'Viewed',
        ' · ',
        'Be an early applicant',
        ' · ',
        'Easy Apply',
        ' · ',
        'Promoted',
    ],
    'card_labels': ['More options', 'Dismiss Senior Full Stack Developer job'],
    'card_img': IMG,
}

# An organic card
ORGANIC: RawJobRecord = {
    'job_id': '4493630969',
    'card_texts': [
        'Cobol Developer',
        'Capgemini',
        'Milan',
        'Posted 7 hours ago\n7 hours ago',
        ' · ',
        'Be an early applicant',
    ],
    'card_labels': ['Dismiss Cobol Developer job'],
    'card_img': '',
}


def test_card_fields_of_a_verified_card() -> None:
    job = parse_job_record(VERIFIED_PROMOTED)
    assert job.job_id == '4438239210'
    assert job.title == 'Junior Software Engineer'
    assert job.company == 'Lexroom'
    assert job.place == 'Milan (Hybrid)'
    assert job.company_img_link == IMG
    assert job.link == 'https://www.linkedin.com/jobs/view/4438239210'


def test_card_fields_of_an_organic_card() -> None:
    job = parse_job_record(ORGANIC)
    assert (job.title, job.company, job.place) == ('Cobol Developer', 'Capgemini', 'Milan')
    assert job.company_img_link == ''


def test_title_falls_back_to_the_visible_line_without_a_dismiss_label() -> None:
    raw: RawJobRecord = {**VERIFIED_PROMOTED, 'card_labels': ['More options']}
    assert parse_job_record(raw).title == 'Junior Software Engineer'


@pytest.mark.parametrize(
    'raw, promoted',
    [
        (VERIFIED_PROMOTED, True),
        (EASY_APPLY_PROMOTED, True),
        (ORGANIC, False),
    ],
)
def test_promoted_cards_are_flagged(raw: RawJobRecord, promoted: bool) -> None:
    assert parse_job_record(raw).promoted is promoted


def test_record_becomes_event_data() -> None:
    data = parse_job_record(ORGANIC).event_data(query='cobol', location='Italy', job_index=3)
    assert data.query == 'cobol'
    assert data.location == 'Italy'
    assert data.job_index == 3
    assert data.job_id == '4493630969'
    assert data.title == 'Cobol Developer'
    assert data.company == 'Capgemini'
    assert data.place == 'Milan'
    assert data.link == 'https://www.linkedin.com/jobs/view/4493630969'


def test_a_card_missing_its_texts_yields_empty_fields() -> None:
    raw: RawJobRecord = {'job_id': '1', 'card_texts': [], 'card_labels': [], 'card_img': ''}
    job = parse_job_record(raw)
    assert (job.title, job.company, job.place, job.promoted) == ('', '', '', False)


@pytest.mark.parametrize(
    'text, expected',
    [
        ('48 results', (48, False)),
        ('1 result', (1, False)),
        ('99+ results', (99, True)),
        ('1,234 results', (1234, False)),
        ('', (None, False)),
        ('No matching jobs found', (None, False)),
    ],
)
def test_results_total(text: str, expected: tuple[int | None, bool]) -> None:
    total = parse_results_total(text)
    assert (total.total, total.capped) == expected
