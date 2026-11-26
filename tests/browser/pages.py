"""Pages shaped as LinkedIn's, holding the strings the unit tests captured live."""

from __future__ import annotations

from html import escape

from linkedin_jobs_scraper.utils.job_record import RawJobDetails, RawJobRecord
from tests.unit.test_job_details import FRESH, REPOSTED, SAFETY_HREF, details
from tests.unit.test_job_record import EASY_APPLY_PROMOTED, ORGANIC, VERIFIED_PROMOTED

# Without an icon of its own a page makes Chrome ask for /favicon.ico
HEAD = '<!doctype html><meta charset="utf-8"><link rel="icon" href="data:,">'
NAVIGATION = '<nav data-testid="primary-nav">Jobs</nav>'

HOME_TEXT = 'Welcome to your professional community'
HOME = f'{HEAD}<p>{HOME_TEXT}</p>'
SIGNED_OUT = f'{HEAD}<form class="login__form">Sign in</form>'

JOBS: dict[str, RawJobDetails] = {
    '4438239210': {
        **REPOSTED,
        'anchors': [
            *REPOSTED['anchors'],
            {'text': 'Apply', 'href': SAFETY_HREF, 'label': 'Apply on company website'},
        ],
        'button_labels': ['More options', 'Save the job'],
    },
    '4492629290': {
        **FRESH,
        'button_labels': ['More options', 'Easy Apply to this job', 'Save the job'],
    },
    '4493630969': details('4493630969', 'Italy · 1 year ago · Over 100 people clicked apply'),
}


def _organic(job_id: str) -> RawJobRecord:
    return {**ORGANIC, 'job_id': job_id}


# A full page of results
CARDS: list[RawJobRecord] = [
    # Without its dismiss label, its title is the visible line of its first paragraph
    {**VERIFIED_PROMOTED, 'card_labels': ['More options']},
    EASY_APPLY_PROMOTED,
    ORGANIC,
    *(_organic(str(4500000000 + index)) for index in range(22)),
]

DETAILS_PATH = '/fake/details/'


def _paragraphs(texts: list[str]) -> str:
    return ''.join('<p>' + escape(text).replace('\n', '<br>') + '</p>' for text in texts)


def _buttons(labels: list[str]) -> str:
    return ''.join(f'<button aria-label="{escape(label)}"></button>' for label in labels)


def _image(src: str) -> str:
    return f'<img src="{escape(src)}">' if src else ''


def _cards(cards: list[RawJobRecord]) -> str:
    html = ''
    for card in cards:
        key = f'job-card-component-ref-{card["job_id"]}'
        html += (
            f'<div role="button" componentkey="{key}"><div componentkey="{key}">'
            f'{_image(card["card_img"])}{_paragraphs(card["card_texts"])}'
            f'{_buttons(card["card_labels"])}</div></div>'
        )
    return html


def job_details(job_id: str) -> str:
    job = JOBS[job_id]
    anchors = ''.join(
        f'<a href="{escape(anchor["href"])}" aria-label="{escape(anchor["label"])}">'
        f'{escape(anchor["text"])}</a>'
        for anchor in job['anchors']
    )
    posting = job['description_html'].replace('<h2 class="cfsjq5">About the job</h2>', '')
    company = ''.join(f'<span>{escape(text)}</span>' for text in job['company_texts'])
    return f"""
        <div data-testid="lazy-column">
            {_image(job['company_img'])}{_paragraphs(job['top_texts'])}{anchors}
            {_buttons(job['button_labels'])}
            <div componentkey="JobDetails_AboutTheJob_{job_id}">
                <h2>About the job</h2>
                <div data-testid="expandable-text-box">{posting}<button>… more</button></div>
            </div>
            <div componentkey="JobDetails_AboutTheCompany_{job_id}">
                <h2>About the company</h2><div><img src="data:,"><p>{company}</p></div>
            </div>
        </div>
    """


# The components of a job arrive empty. The posting fills in first, the company later.
STREAM_DETAILS = """
    function streamDetails(root) {
        ['AboutTheJob', 'AboutTheCompany'].forEach((key, index) => {
            const component = root.querySelector(`[componentkey^="JobDetails_${key}_"]`);
            const contents = [...component.childNodes];
            component.replaceChildren();
            setTimeout(() => component.append(...contents), 150 * (index + 1));
        });
    }
"""


def single_job(job_id: str) -> str:
    if job_id not in JOBS:
        return (
            f'{HEAD}{NAVIGATION}<main><p>Unable to load the page</p><p>Job id provided may not be '
            'valid or the job posting has been removed.</p></main>'
        )
    return (
        f'{HEAD}{NAVIGATION}<main>{job_details(job_id)}</main>'
        f'<script>{STREAM_DETAILS} streamDetails(document.querySelector("main"));</script>'
    )


# A card shows its details once opened, and asks for them again when refused
OPEN_CARDS = f"""
    async function openDetails(jobId) {{
        const response = await fetch('{DETAILS_PATH}' + jobId);
        if (!response.ok) {{
            setTimeout(() => openDetails(jobId), 300);
            return;
        }}
        const panel = document.querySelector('main');
        panel.innerHTML = await response.text();
        streamDetails(panel);
    }}
    document.addEventListener('click', event => {{
        const card = event.target.closest('[role="button"]');
        if (card) {{
            openDetails(card.getAttribute('componentkey').replace(/[^0-9]/g, ''));
        }}
    }});
"""

# The parts a page of results streams in: the first card comes with the page, the others later
SEARCH = (
    f'{HEAD}{NAVIGATION}<button aria-label="Location Italy"></button><p>99+ results</p>'
    f'<main></main><script>{STREAM_DETAILS}{OPEN_CARDS}</script>' + _cards(CARDS[:1]),
    _cards(CARDS[1:]),
)
