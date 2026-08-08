"""Strict field-level validation of every EventData the scraper emits.

Not collected by pytest (the filename does not match `test_*.py`): this is a manual
diagnostic meant to be run against live LinkedIn when the DOM is suspected to have
changed. It asserts the *shape* of every field, not just that it is non-empty, so a
selector that silently starts returning the wrong node is caught.

PYTHONPATH is required: running the file by path puts its own directory on sys.path, not
the working directory holding the package.

    LI_RM_COOKIE=... LI_BCOOKIE=... PYTHONPATH=. LOG_LEVEL=INFO \
        python -u tests/manual/validate_fields.py

A chromedriver on PATH whose major version differs from the local Chrome fails the run
before it starts; PATH="/usr/bin:/bin" hides it and lets Selenium Manager fetch a match.

Environment:
    LI_RM_COOKIE  the remember me credential, with LI_BCOOKIE
    LI_BCOOKIE    the browser id it was issued to
    LI_AT_COOKIE  a session cookie, the fallback when the pair is unavailable
    LIMIT         jobs to scrape, default 30 (>25 also exercises pagination)
    APPLY_LINK    'true' to also capture off-site apply links, default 'false'
    QUERY         search keywords, default 'Software Engineer'
    LOCATION      search location, default 'United Kingdom'
"""
import logging
import os
import re
from urllib.parse import urlparse

from linkedin_jobs_scraper import LinkedinScraper
from linkedin_jobs_scraper.events import Events, EventData, EventMetrics
from linkedin_jobs_scraper.query import Query, QueryOptions, QueryFilters
from linkedin_jobs_scraper.filters import TimeFilters

logging.getLogger('urllib3').setLevel(logging.WARN)
logging.getLogger('selenium').setLevel(logging.WARN)

LIMIT = int(os.environ.get('LIMIT', '30'))
APPLY_LINK = os.environ.get('APPLY_LINK', 'false').lower() == 'true'
QUERY = os.environ.get('QUERY', 'Software Engineer')
LOCATION = os.environ.get('LOCATION', 'United Kingdom')

RELATIVE_DATE = re.compile(r'(\bago\b|just now|^reposted\b)', re.I)
ISO_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
JOB_ID = re.compile(r'^\d{5,}$')

records = []
metrics_seen = []
errors = []


def violations_for(data: EventData, seen_ids: set) -> list:
    """Return the list of rule violations for one record."""
    v = []

    def bad(field, why, value):
        v.append('%-17s %s | got=%r' % (field, why, value))

    if not JOB_ID.match(data.job_id or ''):
        bad('job_id', 'not a numeric LinkedIn id', data.job_id)
    if data.job_id in seen_ids:
        bad('job_id', 'DUPLICATE across the run', data.job_id)

    # The link must point at this very job: that is what proves the card fields and
    # the job id have not drifted apart in the virtualized list.
    u = urlparse(data.link or '')
    if u.scheme != 'https' or not u.netloc.endswith('linkedin.com'):
        bad('link', 'not an https linkedin url', data.link)
    if data.job_id and data.job_id not in (data.link or ''):
        bad('link', 'does not contain job_id (card/link desync)', data.link)
    if '/jobs/view/' not in (data.link or ''):
        bad('link', 'not a /jobs/view/ url', data.link)

    title = data.title or ''
    if not title.strip():
        bad('title', 'empty', title)
    if '\n' in title:
        bad('title', 'contains a newline (hidden a11y copy leaked)', title)
    if title != title.strip():
        bad('title', 'not trimmed', title)
    if re.search(r'\s{2,}', title):
        bad('title', 'spaces not collapsed', title)

    if not (data.company or '').strip():
        bad('company', 'empty', data.company)
    cu = urlparse(data.company_link or '')
    if not data.company_link:
        bad('company_link', 'empty', data.company_link)
    elif cu.scheme != 'https' or not cu.netloc.endswith('linkedin.com'):
        bad('company_link', 'not an https linkedin url', data.company_link)
    elif '/company/' not in data.company_link and '/school/' not in data.company_link:
        bad('company_link', 'not a /company/ or /school/ url', data.company_link)

    if data.company_img_link and urlparse(data.company_img_link).scheme != 'https':
        bad('company_img_link', 'not https', data.company_img_link)

    if not (data.place or '').strip():
        bad('place', 'empty', data.place)

    if data.date and not ISO_DATE.match(data.date):
        bad('date', 'present but not ISO YYYY-MM-DD', data.date)
    if not (data.date_text or '').strip():
        bad('date_text', 'empty', data.date_text)
    elif not RELATIVE_DATE.search(data.date_text):
        bad('date_text', 'does not look like a relative date', data.date_text)
    elif '·' in data.date_text:
        bad('date_text', 'segment separator leaked in', data.date_text)
    elif len(data.date_text) > 40:
        bad('date_text', 'suspiciously long, sibling segments grabbed', data.date_text)

    if not isinstance(data.insights, list):
        bad('insights', 'not a list', data.insights)
    else:
        if not data.insights:
            bad('insights', 'empty list', data.insights)
        for e in data.insights:
            if not isinstance(e, str) or not e.strip():
                bad('insights', 'blank or non-string entry', e)
            elif '\n' in e or re.search(r'\s{2,}', e):
                bad('insights', 'whitespace not normalized', e)

    if len(data.description or '') < 100:
        bad('description', 'shorter than 100 chars', len(data.description or ''))
    if not (data.description_html or '').startswith('<'):
        bad('description_html', 'does not start with a tag', (data.description_html or '')[:40])
    if len(data.description_html or '') < len(data.description or ''):
        bad('description_html', 'shorter than the plain text', len(data.description_html or ''))
    probe = (data.description or '').strip().split('\n')[0][:30]
    if probe and probe not in (data.description_html or ''):
        bad('description_html', 'does not contain the description text', probe)

    if data.apply_link:
        if urlparse(data.apply_link).scheme not in ('http', 'https'):
            bad('apply_link', 'not an http(s) url', data.apply_link)
        if 'linkedin.com/jobs/search' in data.apply_link:
            bad('apply_link', 'points back at the search page', data.apply_link)

    if not isinstance(data.job_index, int) or data.job_index < 0:
        bad('job_index', 'not a non-negative int', data.job_index)

    return v


scraper = LinkedinScraper(headless=True, max_workers=1, slow_mo=0.6)
scraper.on(Events.DATA, lambda data: records.append(data))
scraper.on(Events.METRICS, lambda metrics: metrics_seen.append(str(metrics)))
scraper.on(Events.ERROR, lambda error: errors.append(str(error)))
scraper.on(Events.END, lambda: None)

scraper.run(queries=[Query(
    query=QUERY,
    options=QueryOptions(
        locations=[LOCATION],
        limit=LIMIT,
        apply_link=APPLY_LINK,
        filters=QueryFilters(time=TimeFilters.MONTH),
    ),
)])

print('\n\n================ FIELD VALIDATION ================', flush=True)
print('limit=%d apply_link=%s' % (LIMIT, APPLY_LINK), flush=True)
print('records: %d  errors: %d  metrics: %s' % (len(records), len(errors), metrics_seen), flush=True)

seen = set()
total_violations = 0
for i, record in enumerate(records):
    vs = violations_for(record, seen)
    seen.add(record.job_id)
    if vs:
        total_violations += len(vs)
        print('\n[VIOLATION] record %d job_id=%s title=%r' % (i, record.job_id, record.title[:50]), flush=True)
        for line in vs:
            print('   ', line, flush=True)

print('\n--- coverage per field (non-empty / total) ---', flush=True)
for f in ('job_id', 'link', 'apply_link', 'title', 'company', 'company_link',
          'company_img_link', 'place', 'description', 'description_html',
          'date', 'date_text', 'insights'):
    print('  %-18s %d/%d' % (f, sum(1 for r in records if getattr(r, f)), len(records)), flush=True)

ids = [r.job_id for r in records]
print('\n--- uniqueness / ordering ---', flush=True)
print('  unique job_ids :', len(set(ids)), '/', len(ids), flush=True)
print('  job_index      :', [r.job_index for r in records], flush=True)

print('\n--- fragile fields ---', flush=True)
print('  date_text values:', sorted({r.date_text for r in records})[:15], flush=True)
print('  insights samples:', flush=True)
for r in records[:6]:
    print('     ', r.insights, flush=True)

if APPLY_LINK:
    print('  apply_link values:', flush=True)
    for r in records:
        if not r.apply_link:
            print('      %s -> (none, likely Easy Apply)' % r.job_id, flush=True)
        else:
            note = '  <-- linkedin host, check for mis-capture' if 'linkedin.com' in r.apply_link else ''
            print('      %s -> %s%s' % (r.job_id, r.apply_link[:110], note), flush=True)

print('\nTOTAL VIOLATIONS:', total_violations, flush=True)
print('records collected:', len(records), 'of', LIMIT, flush=True)
print('RESULT:', 'PASS' if (total_violations == 0 and len(records) == LIMIT and not errors)
      else 'REVIEW NEEDED', flush=True)
