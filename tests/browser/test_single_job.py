from __future__ import annotations

from linkedin_jobs_scraper import LinkedinScraper
from linkedin_jobs_scraper.events import EventData, EventNotFound, Events

from .events import record_events
from .fake_linkedin import FakeLinkedin


def test_a_single_job_is_delivered_from_its_own_page(linkedin: FakeLinkedin) -> None:
    scraper = LinkedinScraper(slow_mo=0.2)
    events = record_events(scraper)

    scraper.scrape_job('4438239210', apply_link=True)

    assert events == [
        (
            Events.DATA,
            EventData(
                job_id='4438239210',
                link='https://www.linkedin.com/jobs/view/4438239210',
                apply_link='https://www.ycombinator.com/companies/kapa-ai/jobs/'
                'JPE2ofG-software-engineer-full-stack?utm_source=syn_li',
                title='Junior Software Engineer',
                company='Lexroom',
                company_link='https://www.linkedin.com/company/lex-room/life/',
                company_employee_count='201-500 employees',
                company_img_link='https://media.licdn.com/dms/image/v2/D4D0BAQGnw939z1kvYw/'
                'lex_room_logo',
                place='Milan, Lombardy, Italy',
                description='Lexroom is building the AI platform where legal work gets done.',
                description_html='<div><p class="x">Lexroom is building the AI platform where '
                'legal work gets done.</p></div>',
                date='2026-11-18',
                date_text='Reposted 5 days ago',
                insights=['Hybrid', 'Full-time'],
                salary='30K EUR/yr - 50K EUR/yr',
                applicant_count='Over 100 people clicked apply',
                reposted=True,
            ),
        )
    ]
    assert linkedin.requested == ['/', '/jobs/view/4438239210/']


def test_a_job_that_was_taken_down_is_not_found(linkedin: FakeLinkedin) -> None:
    scraper = LinkedinScraper(slow_mo=0.2)
    events = record_events(scraper)

    scraper.scrape_job('1')

    assert events == [(Events.NOT_FOUND, EventNotFound(job_id='1'))]
    assert linkedin.requested == ['/', '/jobs/view/1/']
