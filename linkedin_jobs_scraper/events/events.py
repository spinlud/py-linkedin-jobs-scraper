from enum import Enum
from typing import NamedTuple
from typing import List


class Events(Enum):
    DATA = 'scraper:data'
    METRICS = 'scraper:metrics'
    BEGIN = 'scraper:begin'
    END = 'scraper:end'
    ERROR = 'scraper:error'
    INVALID_SESSION = 'scraper:invalid-session'
    SESSION_REFRESHED = 'scraper:session-refreshed'
    NOT_FOUND = 'scraper:not-found'


class EventSession(NamedTuple):
    """Carries a session cookie that differs from the one the scraper was given.

    Emitted so that a caller with no persistent Chrome profile, typically running in an
    ephemeral container, can store the cookie itself instead of harvesting a new one by
    hand on the next run.
    """

    li_at: str = ''


class EventBegin(NamedTuple):
    """Emitted once per query/location before scraping starts, carrying LinkedIn's
    approximate total result count (-1 when it could not be parsed)."""
    job_total: int = -1


class EventNotFound(NamedTuple):
    """Emitted when a single-job scrape targets a job that does not exist or is no longer
    available."""
    job_id: str = ''


class EventData(NamedTuple):
    query: str = ''
    location: str = ''
    job_id: str = ''
    job_index: int = -1  # Only for debug
    link: str = ''
    apply_link: str = ''
    title: str = ''
    company: str = ''
    company_link: str = ''
    company_employee_count: str = ''
    company_img_link: str = ''
    place: str = ''
    description: str = ''
    description_html: str = ''
    date: str = ''
    date_text: str = ''
    insights: List[str] = []


class EventMetrics:
    def __init__(self):
        self.processed = 0  # Number of successfully processed jobs
        self.failed = 0  # Number of jobs failed to process
        self.missed = 0  # Number of missed jobs to load during scraping
        self.skipped = 0  # Number of skipped jobs
        self.throttled = 0  # Number of times LinkedIn answered with a 429
        self.pace = 0.0  # Seconds currently slept between jobs

    def __str__(self):
        return f'{{ processed: {self.processed}, failed: {self.failed}, missed: {self.missed}, ' \
               f'skipped: {self.skipped}, throttled: {self.throttled}, pace: {self.pace} }}'
