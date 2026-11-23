"""Turn the raw pieces read off LinkedIn's jobs search-results page into EventData fields.

The in-page JavaScript only collects: ids, texts, hrefs and aria-labels, in document order.
Every decision about what those pieces mean is taken here, where it can be tested against
strings captured from the live page without a browser.
"""
from __future__ import annotations

import re
from typing import NamedTuple, TypedDict

from ..events import EventData
from .constants import JOBS_URL
from .text import normalize_spaces


def _clean(text: str) -> str:
    return normalize_spaces(text).strip()


class RawJobRecord(TypedDict):
    """What the page script returns for one job card."""
    job_id: str
    # innerText of every <p> of the card, in document order: title, company, place, then
    # the optional salary and the footer items ("Viewed", " · ", "Easy Apply", "Promoted")
    card_texts: list[str]
    # aria-label of every button of the card ("More options", "Dismiss <title> job")
    card_labels: list[str]
    card_img: str


class JobRecord(NamedTuple):
    job_id: str
    title: str
    company: str
    place: str
    company_img_link: str
    link: str
    promoted: bool

    def event_data(self, query: str, location: str, job_index: int) -> EventData:
        return EventData(
            query=query,
            location=location,
            job_id=self.job_id,
            job_index=job_index,
            link=self.link,
            title=self.title,
            company=self.company,
            company_img_link=self.company_img_link,
            place=self.place)


class ResultsTotal(NamedTuple):
    # None when the page shows no count; a lower bound when capped ("99+ results")
    total: int | None
    capped: bool


# The card's dismiss button names the job: "Dismiss <title> job"
_DISMISS_LABEL = re.compile(r'^Dismiss (?P<title>.+) job$')

# The card's only marker of a sponsored posting, a footer item of its own
_PROMOTED = 'Promoted'

_RESULTS_TOTAL = re.compile(r'^(?P<count>[\d,]+)(?P<plus>\+?) results?$')


def _title(raw: RawJobRecord) -> str:
    for label in raw['card_labels']:
        match = _DISMISS_LABEL.match(label.strip())
        if match:
            return _clean(match['title'])

    # The title paragraph holds a screen reader line, which may carry a "(Verified job)"
    # suffix, followed by the visible title
    if not raw['card_texts']:
        return ''
    lines = [line for line in raw['card_texts'][0].split('\n') if line.strip()]
    return _clean(lines[-1]) if lines else ''


def parse_job_record(raw: RawJobRecord) -> JobRecord:
    texts = [_clean(text) for text in raw['card_texts']]
    job_id = raw['job_id']

    return JobRecord(
        job_id=job_id,
        title=_title(raw),
        company=texts[1] if len(texts) > 1 else '',
        place=texts[2] if len(texts) > 2 else '',
        company_img_link=raw['card_img'],
        link=f'{JOBS_URL}/view/{job_id}',
        promoted=_PROMOTED in texts[3:])


def parse_results_total(text: str) -> ResultsTotal:
    match = _RESULTS_TOTAL.match(_clean(text))
    if not match:
        return ResultsTotal(total=None, capped=False)
    return ResultsTotal(total=int(match['count'].replace(',', '')), capped=bool(match['plus']))
