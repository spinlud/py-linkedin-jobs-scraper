from enum import Enum
from typing import NamedTuple
from typing import List


class Events(Enum):
    DATA = 'scraper:data'
    METRICS = 'scraper:metrics'
    END = 'scraper:end'
    ERROR = 'scraper:error'
    INVALID_SESSION = 'scraper:invalid-session'


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

    def __str__(self):
        return f'{{ processed: {self.processed}, failed: {self.failed}, missed: {self.missed}, skipped: {self.skipped} }}'
