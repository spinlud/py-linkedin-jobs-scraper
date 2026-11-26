from __future__ import annotations

from linkedin_jobs_scraper import LinkedinScraper
from linkedin_jobs_scraper.events import EventBegin, EventData, Events
from linkedin_jobs_scraper.filters import OnSiteOrRemoteFilters, TimeFilters, TypeFilters
from linkedin_jobs_scraper.query import Query, QueryFilters, QueryOptions

from .events import record_events
from .fake_linkedin import FakeLinkedin

DESCRIPTION = 'Lexroom is building the AI platform where legal work gets done.'
CARD_IMAGE = 'https://media.licdn.com/dms/image/v2/D4D0BAQGnw939z1kvYw/company-logo_100_100/x.png'
PANEL_IMAGE = 'https://media.licdn.com/dms/image/v2/D4D0BAQGnw939z1kvYw/lex_room_logo'

VERIFIED = EventData(
    query='engineer',
    location='103350119',
    resolved_location='Italy',
    job_id='4438239210',
    job_index=0,
    link='https://www.linkedin.com/jobs/view/4438239210',
    apply_link='https://www.ycombinator.com/companies/kapa-ai/jobs/'
    'JPE2ofG-software-engineer-full-stack?utm_source=syn_li',
    title='Junior Software Engineer',
    company='Lexroom',
    company_link='https://www.linkedin.com/company/lex-room/life/',
    company_employee_count='201-500 employees',
    company_img_link=CARD_IMAGE,
    place='Milan (Hybrid)',
    description=DESCRIPTION,
    description_html=f'<div><p class="x">{DESCRIPTION}</p></div>',
    date='2026-11-18',
    date_text='Reposted 5 days ago',
    insights=['Hybrid', 'Full-time'],
    salary='30K EUR/yr - 50K EUR/yr',
    applicant_count='Over 100 people clicked apply',
    reposted=True,
)
EASY_APPLY = VERIFIED._replace(
    job_id='4492629290',
    job_index=1,
    link='https://www.linkedin.com/jobs/view/4492629290',
    apply_link='',
    title='Senior Full Stack Developer',
    company='CardTrader',
    place='Padua (On-site)',
    date='2026-11-23',
    date_text='3 hours ago',
    is_easy_apply=True,
    applicant_count='13 applicants',
    reposted=False,
)
ORGANIC = VERIFIED._replace(
    job_id='4493630969',
    job_index=2,
    link='https://www.linkedin.com/jobs/view/4493630969',
    apply_link='',
    title='Cobol Developer',
    company='Capgemini',
    company_img_link=PANEL_IMAGE,
    place='Milan',
    date='2025-11-23',
    date_text='1 year ago',
    reposted=False,
)
BEGIN = EventBegin(total=99, total_capped=True, location='103350119', resolved_location='Italy')


def test_a_search_delivers_the_jobs_of_its_cards(linkedin: FakeLinkedin) -> None:
    scraper = LinkedinScraper(slow_mo=0.2)
    events = record_events(scraper)

    options = QueryOptions(locations=['103350119'], limit=3, apply_link=True)
    scraper.run(Query(query='engineer', options=options))

    metrics = {
        'processed': 3,
        'failed': 0,
        'missed': 0,
        'skipped': 0,
        'throttled': 0,
        'pace': 0.2,
    }
    assert events == [
        (Events.BEGIN, BEGIN),
        (Events.DATA, VERIFIED),
        (Events.DATA, EASY_APPLY),
        (Events.DATA, ORGANIC),
        (Events.METRICS, metrics),
        (Events.END, None),
    ]
    assert linkedin.requested == [
        '/',
        '/jobs/search-results/?keywords=engineer&geoId=103350119&start=0',
        '/fake/details/4438239210',
        '/fake/details/4492629290',
        '/fake/details/4493630969',
    ]


def test_a_search_skips_promoted_jobs_and_slows_down_when_refused(linkedin: FakeLinkedin) -> None:
    linkedin.throttled_once.add('4493630969')
    scraper = LinkedinScraper(slow_mo=0.2)
    events = record_events(scraper)

    filters = QueryFilters(
        time=TimeFilters.DAY,
        type=[TypeFilters.FULL_TIME],
        on_site_or_remote=[OnSiteOrRemoteFilters.REMOTE, OnSiteOrRemoteFilters.HYBRID],
    )
    options = QueryOptions(
        locations=['103350119'], limit=1, filters=filters, skip_promoted_jobs=True
    )
    scraper.run(Query(query='engineer', options=options))

    metrics = {
        'processed': 1,
        'failed': 0,
        'missed': 0,
        'skipped': 2,
        'throttled': 1,
        'pace': 0.4,
    }
    assert events == [
        (Events.BEGIN, BEGIN),
        (Events.DATA, ORGANIC),
        (Events.METRICS, metrics),
        (Events.END, None),
    ]
    assert linkedin.requested == [
        '/',
        '/jobs/search-results/?keywords=engineer&geoId=103350119&f_TPR=r86400'
        '&f_SAL=f_SA_id_225001%3A272001%2C1621001%24f_SA_id_226001%3A272015&start=0',
        '/fake/details/4493630969',
        '/fake/details/4493630969',
    ]
