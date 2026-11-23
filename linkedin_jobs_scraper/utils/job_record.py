"""Turn the raw pieces read off LinkedIn's job pages into EventData fields.

The in-page JavaScript only collects: ids, texts, hrefs and aria-labels, in document order.
Every decision about what those pieces mean is taken here, where it can be tested against
strings captured from the live page without a browser.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import NamedTuple, TypedDict
from urllib.parse import parse_qs, urlsplit

from ..events import EventData
from .constants import JOBS_URL
from .dates import parse_relative_date
from .text import clean_applicant_count, normalize_spaces


def _clean(text: str) -> str:
    return normalize_spaces(text).strip()


def _job_link(job_id: str) -> str:
    return f'{JOBS_URL}/view/{job_id}'


class RawJobRecord(TypedDict):
    """What the page script returns for one job card."""
    job_id: str
    # innerText of every <p> of the card, in document order: title, company, place, then
    # the optional salary, tag and benefits pills and the footer items ("Viewed", " · ",
    # "Easy Apply", "Promoted")
    card_texts: list[str]
    # aria-label of every button of the card ("More options", "Dismiss <title> job")
    card_labels: list[str]
    card_img: str


class RawAnchor(TypedDict):
    text: str
    href: str
    # aria-label, '' when absent
    label: str


class RawJobDetails(TypedDict):
    """What the page script returns for the detail components of one job, the same on the
    search-results panel and on the single job page."""
    job_id: str
    # innerText of every <p> above the "About the job" component, in document order: company,
    # title, the top line ("<place> · <date> · <applicants>"), then whatever follows
    top_texts: list[str]
    # Every anchor above the "About the job" component, in document order
    anchors: list[RawAnchor]
    # aria-label of every button above the "About the job" component
    button_labels: list[str]
    company_img: str
    # innerText and innerHTML of the posting's text box in the "About the job" component, its
    # expand toggle included; of the whole component, heading included, when it has no box
    description_text: str
    description_html: str
    # Leaf texts of the "About the company" component
    company_texts: list[str]


class JobDetails(NamedTuple):
    job_id: str
    title: str
    company: str
    place: str
    company_img_link: str
    date_text: str
    date: str
    reposted: bool
    applicant_count: str
    salary: str
    insights: list[str]
    is_easy_apply: bool
    # The decoded off-site target of an external apply anchor; '' for Easy Apply and for an
    # external apply control that is a button with no href
    apply_link: str
    company_link: str
    company_employee_count: str
    description: str
    description_html: str

    def event_data(self, query: str = '', location: str = '', job_index: int = -1) -> EventData:
        return EventData(
            query=query,
            location=location,
            job_id=self.job_id,
            job_index=job_index,
            link=_job_link(self.job_id),
            apply_link=self.apply_link,
            title=self.title,
            company=self.company,
            company_link=self.company_link,
            company_employee_count=self.company_employee_count,
            company_img_link=self.company_img_link,
            place=self.place,
            description=self.description,
            description_html=self.description_html,
            date=self.date,
            date_text=self.date_text,
            insights=self.insights,
            salary=self.salary,
            is_easy_apply=self.is_easy_apply,
            applicant_count=self.applicant_count,
            reposted=self.reposted)


class JobRecord(NamedTuple):
    job_id: str
    title: str
    company: str
    place: str
    company_img_link: str
    link: str
    promoted: bool
    benefits: list[str]

    def event_data(self, query: str, location: str, job_index: int,
                   details: JobDetails | None = None) -> EventData:
        # The card's own fields win over the panel's, which shows the same job differently
        # ("Milan, Lombardy, Italy" on the panel against "Milan (Hybrid)" on the card)
        base = details.event_data() if details else EventData()
        return base._replace(
            query=query,
            location=location,
            job_id=self.job_id,
            job_index=job_index,
            link=self.link,
            title=self.title or base.title,
            company=self.company or base.company,
            company_img_link=self.company_img_link or base.company_img_link,
            place=self.place or base.place,
            benefits=self.benefits)


class ResultsTotal(NamedTuple):
    # None when the page shows no count; a lower bound when capped ("99+ results")
    total: int | None
    capped: bool


# The card's dismiss button names the job: "Dismiss <title> job"
_DISMISS_LABEL = re.compile(r'^Dismiss (?P<title>.+) job$')

# The card's only marker of a sponsored posting, a footer item of its own
_PROMOTED = 'Promoted'

# The card's benefits pill lists benefit names, optionally followed by a remainder
# ("Medical, Vision, Dental, 401(k), +1 benefit"), or holds only a count ("9 benefits"). A
# list shown without the trailing word is told apart from the card's other pills by its names.
_BENEFITS_SUFFIX = re.compile(r'\s*\bbenefits?$', re.IGNORECASE)
_BENEFITS_REMAINDER = re.compile(r'^\+?\d+$')
_BENEFIT_NAMES = frozenset({
    'Medical', 'Vision', 'Dental', '401(k)', 'Pension plan', 'Paid maternity leave',
    'Paid paternity leave', 'Commuter benefits', 'Student loan assistance', 'Tuition assistance',
    'Disability insurance', 'Child care support'})

_RESULTS_TOTAL = re.compile(r'^(?P<count>[\d,]+)(?P<plus>\+?) results?$')

# The date segment of the top line is recognised by its shape, never by its position, since
# any segment of that line may be absent
_DATE_SEGMENT = re.compile(r'\bago\b|\bjust now\b', re.IGNORECASE)

_REPOSTED = re.compile(r'^Reposted\b', re.IGNORECASE)

# A pay range carries a period ("30K EUR/yr - 50K EUR/yr", "$100K/yr - $150K/yr")
_SALARY = re.compile(r'\d.*/(?:yr|mo|wk|day|hr)\b')

_EASY_APPLY_LABEL = re.compile(r'^Easy Apply\b')
_EXTERNAL_APPLY_LABEL = 'Apply on company website'

# LinkedIn routes every off-site link through this redirect, the target in its `url` param
_SAFETY_REDIRECT_PATH = '/safety/go/'

_COMPANY_PATH = re.compile(r'^/company/[^/]+/')
_EMPLOYEE_COUNT = re.compile(r'\bemployees?$')

# Neither the component's own heading nor the text box's expand toggle is part of the posting
_ABOUT_HEADING_TEXT = re.compile(r'^\s*About the job\s*')
_ABOUT_HEADING_HTML = re.compile(r'<h2\b[^>]*>\s*About the job\s*</h2>')
_EXPAND_TOGGLE_TEXT = re.compile(r'\s*…\s*more\s*$')
_EXPAND_TOGGLE_HTML = re.compile(r'<button\b[^>]*>.*?</button>', re.DOTALL)


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


def _benefits(texts: list[str]) -> list[str]:
    for text in texts:
        has_suffix = bool(_BENEFITS_SUFFIX.search(text))
        items = [item.strip() for item in _BENEFITS_SUFFIX.sub('', text).split(',')]
        names = [item for item in items if item and not _BENEFITS_REMAINDER.match(item)]
        if has_suffix or (names and all(name in _BENEFIT_NAMES for name in names)):
            return names
    return []


def parse_job_record(raw: RawJobRecord) -> JobRecord:
    texts = [_clean(text) for text in raw['card_texts']]
    job_id = raw['job_id']

    return JobRecord(
        job_id=job_id,
        title=_title(raw),
        company=texts[1] if len(texts) > 1 else '',
        place=texts[2] if len(texts) > 2 else '',
        company_img_link=raw['card_img'],
        link=_job_link(job_id),
        promoted=_PROMOTED in texts[3:],
        benefits=_benefits(texts[3:]))


def _top_line(texts: list[str]) -> list[str]:
    for text in texts:
        segments = [segment for segment in (_clean(part) for part in text.split('·')) if segment]
        if any(_DATE_SEGMENT.search(segment) or clean_applicant_count(segment)
               for segment in segments):
            return segments
    return []


def _is_pill(anchor: RawAnchor, job_id: str, title: str) -> bool:
    # A pill links back to the job it describes: on the search panel to the results with the
    # job selected, on the single job page to the job itself. The title links there too.
    href = anchor['href']
    text = _clean(anchor['text'])
    points_at_job = f'currentJobId={job_id}' in href or f'/jobs/view/{job_id}/' in href
    return points_at_job and bool(text) and text != title


def _decode_safety_redirect(href: str) -> str:
    parts = urlsplit(href)
    if parts.path != _SAFETY_REDIRECT_PATH:
        return ''
    return parse_qs(parts.query).get('url', [''])[0]


def _apply_link(anchors: list[RawAnchor]) -> str:
    for anchor in anchors:
        if anchor['label'] == _EXTERNAL_APPLY_LABEL:
            target = _decode_safety_redirect(anchor['href'])
            if target:
                return target
    return ''


def _company_link(anchors: list[RawAnchor]) -> str:
    for anchor in anchors:
        parts = urlsplit(anchor['href'])
        if _COMPANY_PATH.match(parts.path):
            return f'{parts.scheme}://{parts.netloc}{parts.path}'
    return ''


def parse_job_details(raw: RawJobDetails, now: datetime) -> JobDetails:
    job_id = raw['job_id']
    texts = [_clean(text) for text in raw['top_texts']]
    title = texts[1] if len(texts) > 1 else ''

    segments = _top_line(texts)
    date_text = next((segment for segment in segments if _DATE_SEGMENT.search(segment)), '')
    applicant_count = next(
        (count for count in (clean_applicant_count(segment) for segment in segments) if count), '')
    place = segments[0] if segments and segments[0] not in (date_text, applicant_count) else ''

    pills = [_clean(anchor['text']) for anchor in raw['anchors'] if _is_pill(anchor, job_id, title)]
    salary = next((text for text in pills if _SALARY.search(text)), '')
    labels = raw['button_labels'] + [anchor['label'] for anchor in raw['anchors']]
    company_texts = [_clean(text) for text in raw['company_texts']]

    return JobDetails(
        job_id=job_id,
        title=title,
        company=texts[0] if texts else '',
        place=place,
        company_img_link=raw['company_img'],
        date_text=date_text,
        date=parse_relative_date(date_text, now),
        reposted=bool(_REPOSTED.match(date_text)),
        applicant_count=applicant_count,
        salary=salary,
        insights=[text for text in pills if text != salary],
        is_easy_apply=any(_EASY_APPLY_LABEL.match(label) for label in labels),
        apply_link=_apply_link(raw['anchors']),
        company_link=_company_link(raw['anchors']),
        company_employee_count=next(
            (text for text in company_texts if _EMPLOYEE_COUNT.search(text)), ''),
        description=_EXPAND_TOGGLE_TEXT.sub(
            '', _ABOUT_HEADING_TEXT.sub('', raw['description_text'])).strip(),
        description_html=_EXPAND_TOGGLE_HTML.sub(
            '', _ABOUT_HEADING_HTML.sub('', raw['description_html'], count=1)).strip())


def parse_results_total(text: str) -> ResultsTotal:
    match = _RESULTS_TOTAL.match(_clean(text))
    if not match:
        return ResultsTotal(total=None, capped=False)
    return ResultsTotal(total=int(match['count'].replace(',', '')), capped=bool(match['plus']))
