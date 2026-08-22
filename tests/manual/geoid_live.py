"""Live smoke test of a geoId-pinned search against real LinkedIn.

Uses a pre-authenticated Chrome profile so no credential env vars are needed.
Ensure no other Chrome instance holds the profile before running.

    PATH="/usr/bin:/bin" PYTHONPATH=. \
        python tests/manual/geoid_live.py

PATH="/usr/bin:/bin" hides any stray chromedriver so Selenium Manager fetches a
match for the local Chrome.
"""
import logging
import sys

from linkedin_jobs_scraper import LinkedinScraper
from linkedin_jobs_scraper.events import Events, EventData
from linkedin_jobs_scraper.query import Query, QueryOptions, Location

logging.getLogger('urllib3').setLevel(logging.WARN)
logging.getLogger('selenium').setLevel(logging.WARN)

USER_DATA_DIR = '/Users/ludovicofabbri/.linkedin-jobs-scraper'
GEO_ID = '103644278'
LABEL = 'United States'
LIMIT = 5

locations_seen = []
places_seen = []
errors = []


def on_data(data: EventData) -> None:
    locations_seen.append(data.location)
    places_seen.append(data.place)


def on_error(err) -> None:
    errors.append(str(err))


def on_end() -> None:
    pass


scraper = LinkedinScraper(
    headless=True,
    max_workers=1,
    slow_mo=0.8,
    chrome_user_data_dir=USER_DATA_DIR,
)
scraper.on(Events.DATA, on_data)
scraper.on(Events.ERROR, on_error)
scraper.on(Events.END, on_end)

scraper.run(queries=[Query(
    query='Software Engineer',
    options=QueryOptions(
        locations=[Location(geo_id=GEO_ID, name=LABEL)],
        limit=LIMIT,
    ),
)])

print('\n\n================ GEOID LIVE SMOKE ================', flush=True)
print('records: %d  errors: %d' % (len(places_seen), len(errors)), flush=True)
if errors:
    for e in errors:
        print('  ERROR:', e[:300], flush=True)

print('data.location values:', sorted(set(locations_seen)), flush=True)
print('data.place values:', flush=True)
for p in places_seen:
    print('   ', p, flush=True)

failures = 0


def check(description: str, condition: bool) -> None:
    global failures
    status = 'PASS' if condition else 'FAIL'
    if not condition:
        failures += 1
    print('[%s] %s' % (status, description), flush=True)


print('\n--- assertions ---', flush=True)
check('at least one job emitted', len(places_seen) >= 1)
check("every EventData.location == '%s'" % LABEL,
      len(locations_seen) > 0 and all(loc == LABEL for loc in locations_seen))

print('\nTOTAL FAILURES:', failures, flush=True)
print('RESULT:', 'PASS' if failures == 0 else 'FAIL', flush=True)
sys.exit(1 if failures else 0)
