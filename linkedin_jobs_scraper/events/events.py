from enum import Enum
from typing import NamedTuple


class Events(Enum):
    DATA = 'scraper:data'
    END = 'scraper:end'
    ERROR = 'scraper:error'
    INVALID_SESSION = 'scraper:invalid-session'


class EventData(NamedTuple):
    query: str = ''
    location: str = ''
    job_id: str = ''
    link: str = ''
    apply_link: str = ''
    title: str = ''
    company: str = ''
    place: str = ''
    description: str = ''
    description_html: str = ''
    date: str = ''
    seniority_level: str = ''
    job_function: str = ''
    employment_type: str = ''
    industries: str = ''
