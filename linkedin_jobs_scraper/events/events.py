from enum import Enum
from typing import NamedTuple


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
    """Emitted once per query/location before scraping starts, carrying LinkedIn's total
    result count: None when it could not be read, and a lower bound when total_capped is
    True, which is how LinkedIn's "N+ results" reads. location is the location the search
    was asked for, as EventData.location carries it ('' for the account's current one), and
    resolved_location is the location LinkedIn applied to the search, as its location
    control names it, '' when unreadable."""

    total: int | None = None
    total_capped: bool = False
    location: str = ''
    resolved_location: str = ''


class EventNotFound(NamedTuple):
    """Emitted when a single-job scrape targets a job that does not exist or is no longer
    available."""

    job_id: str = ''


class EventData(NamedTuple):
    query: str = ''
    location: str = ''
    resolved_location: str = ''  # The location LinkedIn applied to the search; '' for a single job
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
    insights: list[str] = []
    salary: str = ''
    is_easy_apply: bool = False
    applicant_count: str = ''
    benefits: list[str] = []
    reposted: bool = False


class EventMetrics:
    def __init__(self):
        self.processed = 0  # Number of successfully processed jobs
        self.failed = 0  # Number of jobs failed to process
        self.missed = 0  # Number of missed jobs to load during scraping
        self.skipped = 0  # Number of skipped jobs
        self.throttled = 0  # Number of times LinkedIn answered with a 429
        self.pace = 0.0  # Seconds currently slept between jobs

    def __str__(self):
        return (
            f'{{ processed: {self.processed}, failed: {self.failed}, missed: {self.missed}, '
            f'skipped: {self.skipped}, throttled: {self.throttled}, pace: {self.pace} }}'
        )
