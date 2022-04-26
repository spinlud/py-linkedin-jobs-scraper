from enum import Enum
from typing import NamedTuple
from typing import List


class Events(Enum):
    DATA = 'scraper:data'
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
    insights: List[str] = []
