"""Offline tests for the raw detail panel -> EventData seam.

Every input is a string captured from the detail panel of LinkedIn's jobs search-results page
and from the single job page /jobs/view/<id>/.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from linkedin_jobs_scraper.utils.job_record import (RawAnchor, RawJobDetails, RawJobRecord,
                                                    parse_job_details, parse_job_record)

NOW = datetime(2026, 11, 23, 18, 30)

PILL_HREF = 'https://www.linkedin.com/jobs/search-results/?currentJobId={}&eBP=NOT_ELIGIBLE_FOR_CHARGING'
PREMIUM_HREF = 'https://www.linkedin.com/premium/products/?upsellOrderOrigin=Tracking'
SAFETY_HREF = ('https://www.linkedin.com/safety/go/?url=https%3A%2F%2Fwww%2Eycombinator%2Ecom%2F'
               'companies%2Fkapa-ai%2Fjobs%2FJPE2ofG-software-engineer-full-stack%3Futm_source%3D'
               'syn_li&urlhash=LMDb&mt=sVOR7orzfqXd_Mbv33UVITF2JI0VfDfn')


def pill(job_id: str, text: str) -> RawAnchor:
    return {'text': text, 'href': PILL_HREF.format(job_id), 'label': ''}


def details(job_id: str, top_line: str) -> RawJobDetails:
    return {
        'job_id': job_id,
        'top_texts': ['Lexroom', 'Junior Software Engineer ', top_line,
                      'Promoted by hirer · Responses managed off LinkedIn',
                      'Get AI-powered advice on this job and more exclusive features with Premium.'],
        'anchors': [
            {'text': 'Lexroom', 'href': 'https://www.linkedin.com/company/lex-room/life/',
             'label': 'Company, Lexroom.'},
            {'text': 'Lexroom', 'href': 'https://www.linkedin.com/company/lex-room/life/', 'label': ''},
            {'text': 'Junior Software Engineer',
             'href': f'https://www.linkedin.com/jobs/view/{job_id}/?trackingId=INHU', 'label': ''},
            pill(job_id, '30K EUR/yr - 50K EUR/yr'),
            pill(job_id, 'Hybrid'),
            pill(job_id, 'Full-time'),
            {'text': 'Activate Premium for €0', 'href': PREMIUM_HREF, 'label': ''},
        ],
        'button_labels': ['More options', 'Apply on company website', 'Save the job'],
        'company_img': 'https://media.licdn.com/dms/image/v2/D4D0BAQGnw939z1kvYw/lex_room_logo',
        'description_text': 'About the job\n\nLexroom is building the AI platform where legal work gets done.',
        'description_html': '<div><h2 class="cfsjq5">About the job</h2><p class="x">Lexroom is '
                            'building the AI platform where legal work gets done.</p></div>',
        'company_texts': ['Lexroom', '36,320 followers', 'Follow', 'Technology, Information and Internet',
                          ' • ', '201-500 employees', ' • ', '330 on LinkedIn', '…', ' more'],
    }


REPOSTED = details('4438239210', 'Milan, Lombardy, Italy · Reposted 5 days ago · Over 100 people clicked apply')
FRESH = details('4492629290', 'Padua, Veneto, Italy · 3 hours ago · 13 applicants')


def test_top_line_of_a_reposted_job() -> None:
    job = parse_job_details(REPOSTED, NOW)
    assert job.place == 'Milan, Lombardy, Italy'
    assert job.date_text == 'Reposted 5 days ago'
    assert job.date == '2026-11-18'
    assert job.reposted is True
    assert job.applicant_count == 'Over 100 people clicked apply'


def test_top_line_of_a_fresh_job() -> None:
    job = parse_job_details(FRESH, NOW)
    assert job.place == 'Padua, Veneto, Italy'
    assert job.date_text == '3 hours ago'
    assert job.date == '2026-11-23'
    assert job.reposted is False
    assert job.applicant_count == '13 applicants'


@pytest.mark.parametrize('top_line, place, date_text, applicant_count', [
    ('Italy · 1 year ago · Over 100 people clicked apply', 'Italy', '1 year ago',
     'Over 100 people clicked apply'),
    ('Bologna, Emilia-Romagna, Italy · 5 days ago · 94 people clicked apply',
     'Bologna, Emilia-Romagna, Italy', '5 days ago', '94 people clicked apply'),
    ('Milan, Lombardy, Italy · 3 weeks ago · Over 100 applicants', 'Milan, Lombardy, Italy',
     '3 weeks ago', 'Over 100 applicants'),
    ('Milan, Lombardy, Italy · 2 days ago', 'Milan, Lombardy, Italy', '2 days ago', ''),
    ('Milan, Lombardy, Italy · 12 applicants', 'Milan, Lombardy, Italy', '', '12 applicants'),
    ('2 days ago · 12 applicants', '', '2 days ago', '12 applicants'),
])
def test_top_line_segments_may_be_missing(top_line: str, place: str, date_text: str,
                                          applicant_count: str) -> None:
    job = parse_job_details(details('1', top_line), NOW)
    assert (job.place, job.date_text, job.applicant_count) == (place, date_text, applicant_count)


@pytest.mark.parametrize('date_text, date', [
    ('Reposted 12 minutes ago', '2026-11-23'),
    ('3 hours ago', '2026-11-23'),
    ('1 day ago', '2026-11-22'),
    ('Reposted 2 weeks ago', '2026-11-09'),
    ('4 months ago', '2026-07-26'),
    ('1 year ago', '2025-11-23'),
])
def test_dates_are_approximated_from_the_relative_text(date_text: str, date: str) -> None:
    job = parse_job_details(details('1', f'Italy · {date_text} · 10 applicants'), NOW)
    assert (job.date_text, job.date) == (date_text, date)


def test_a_panel_without_a_top_line_yields_empty_fields() -> None:
    raw: RawJobDetails = {**FRESH, 'top_texts': ['CardTrader', 'Senior Full Stack Developer']}
    job = parse_job_details(raw, NOW)
    assert (job.place, job.date_text, job.date, job.applicant_count, job.reposted) == \
        ('', '', '', '', False)


def test_salary_pill_is_separated_from_the_insights() -> None:
    job = parse_job_details(REPOSTED, NOW)
    assert job.salary == '30K EUR/yr - 50K EUR/yr'
    assert job.insights == ['Hybrid', 'Full-time']


def test_without_a_salary_pill_every_pill_is_an_insight() -> None:
    raw: RawJobDetails = {**FRESH, 'anchors': [pill('4492629290', 'On-site'),
                                               pill('4492629290', 'Full-time'),
                                               pill('4492629290', 'IV Therapy')]}
    job = parse_job_details(raw, NOW)
    assert job.salary == ''
    assert job.insights == ['On-site', 'Full-time', 'IV Therapy']


def test_dollar_salary_pill() -> None:
    raw: RawJobDetails = {**FRESH, 'anchors': [pill('4492629290', '$100K/yr - $150K/yr'),
                                               pill('4492629290', 'Remote')]}
    job = parse_job_details(raw, NOW)
    assert (job.salary, job.insights) == ('$100K/yr - $150K/yr', ['Remote'])


def test_pills_of_the_single_job_page_point_at_the_job_view() -> None:
    raw: RawJobDetails = {**FRESH, 'anchors': [
        {'text': 'On-site', 'href': 'https://www.linkedin.com/jobs/view/4492629290/', 'label': ''},
        {'text': 'Full-time', 'href': 'https://www.linkedin.com/jobs/view/4492629290/', 'label': ''}]}
    assert parse_job_details(raw, NOW).insights == ['On-site', 'Full-time']


def test_an_external_job_decodes_its_safety_redirect() -> None:
    raw: RawJobDetails = {**REPOSTED, 'anchors': [
        *REPOSTED['anchors'],
        {'text': 'Apply', 'href': SAFETY_HREF, 'label': 'Apply on company website'}],
        'button_labels': ['More options', 'Save the job']}
    job = parse_job_details(raw, NOW)
    assert job.is_easy_apply is False
    assert job.apply_link == ('https://www.ycombinator.com/companies/kapa-ai/jobs/'
                              'JPE2ofG-software-engineer-full-stack?utm_source=syn_li')


def test_an_external_apply_button_has_no_link_to_decode() -> None:
    job = parse_job_details(REPOSTED, NOW)
    assert (job.is_easy_apply, job.apply_link) == (False, '')


def test_an_easy_apply_job() -> None:
    raw: RawJobDetails = {**FRESH, 'button_labels': ['More options', 'Easy Apply to this job',
                                                     'Save the job']}
    job = parse_job_details(raw, NOW)
    assert (job.is_easy_apply, job.apply_link) == (True, '')


def test_company_fields() -> None:
    job = parse_job_details(REPOSTED, NOW)
    assert job.company == 'Lexroom'
    assert job.title == 'Junior Software Engineer'
    assert job.company_link == 'https://www.linkedin.com/company/lex-room/life/'
    assert job.company_employee_count == '201-500 employees'


def test_description_drops_the_heading() -> None:
    job = parse_job_details(REPOSTED, NOW)
    assert job.description == 'Lexroom is building the AI platform where legal work gets done.'
    assert job.description_html == ('<div><p class="x">Lexroom is building the AI platform where '
                                    'legal work gets done.</p></div>')


def test_description_drops_the_expand_toggle() -> None:
    raw: RawJobDetails = {
        **REPOSTED,
        'description_text': 'Provide coordinated, family-centered nursing care.\n… more',
        'description_html': '<p class="cfsjxw">Provide coordinated, family-centered nursing care.</p>'
                            '<button class="cfska5 cfska4" type="button"><span>… more</span></button>'}
    job = parse_job_details(raw, NOW)
    assert job.description == 'Provide coordinated, family-centered nursing care.'
    assert job.description_html == '<p class="cfsjxw">Provide coordinated, family-centered nursing care.</p>'


def test_card_and_panel_merge_into_event_data() -> None:
    card: RawJobRecord = {
        'job_id': '4438239210',
        'card_texts': ['Junior Software Engineer (Verified job)\nJunior Software Engineer ', 'Lexroom',
                       'Milan (Hybrid)', '30K EUR/yr - 50K EUR/yr', 'Viewed', ' · ', 'Promoted'],
        'card_labels': ['More options', 'Dismiss Junior Software Engineer job'],
        'card_img': 'https://media.licdn.com/card.png',
    }
    data = parse_job_record(card).event_data(
        query='q', location='Italy', job_index=0, details=parse_job_details(REPOSTED, NOW))
    assert data.place == 'Milan (Hybrid)'
    assert data.company_img_link == 'https://media.licdn.com/card.png'
    assert data.description.startswith('Lexroom is building')
    assert data.date_text == 'Reposted 5 days ago'
    assert data.salary == '30K EUR/yr - 50K EUR/yr'
    assert data.company_link == 'https://www.linkedin.com/company/lex-room/life/'
    assert data.link == 'https://www.linkedin.com/jobs/view/4438239210'


def test_single_job_event_data_comes_from_the_panel_alone() -> None:
    data = parse_job_details(REPOSTED, NOW).event_data()
    assert data.job_id == '4438239210'
    assert (data.title, data.company, data.place) == ('Junior Software Engineer', 'Lexroom',
                                                      'Milan, Lombardy, Italy')
    assert data.link == 'https://www.linkedin.com/jobs/view/4438239210'
    assert data.applicant_count == 'Over 100 people clicked apply'
    assert data.benefits == []


def _card_with(*metadata: str) -> RawJobRecord:
    return {'job_id': '1',
            'card_texts': ['Registered Nurse', 'Biograph', 'San Mateo, CA (On-site)', *metadata,
                           'Posted 2 months ago\n2 months ago'],
            'card_labels': [], 'card_img': ''}


@pytest.mark.parametrize('metadata, benefits', [
    (('Primary Care', ' • ', 'Day', ' • ', 'Medical, Vision, Dental, 401(k), +1 benefit'),
     ['Medical', 'Vision', 'Dental', '401(k)']),
    (('Aesthetic', ' • ', '401(k) benefit'), ['401(k)']),
    (('IV Therapy', ' • ', 'Day', ' • ', 'Medical benefit'), ['Medical']),
    (('Wound Care +1', ' • ', 'Medical, Vision, Dental, 401(k)'), ['Medical', 'Vision', 'Dental', '401(k)']),
    (('$85K/yr - $95K/yr', ' • ', 'Obstetrics & Gynecology', ' • ', 'Day', ' • ', 'Medical, Vision, Dental'),
     ['Medical', 'Vision', 'Dental']),
    (('Telehealth +1', ' • ', 'Day', ' • ', 'Medical, 401(k)'), ['Medical', '401(k)']),
    (('Primary Care', ' • ', '9 benefits'), []),
    (('Medical-Surgical +1', ' • ', 'Night'), []),
    ((), []),
])
def test_benefits_come_from_the_card_pill(metadata: tuple[str, ...], benefits: list[str]) -> None:
    data = parse_job_record(_card_with(*metadata)).event_data(query='', location='', job_index=0)
    assert data.benefits == benefits
