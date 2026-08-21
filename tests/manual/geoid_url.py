"""Offline probe of __build_search_url for geoId vs location= handling.

Needs no live LinkedIn: it calls the name-mangled private static
LinkedinScraper._LinkedinScraper__build_search_url and asserts on the parsed
query params of the returned url.

PYTHONPATH is required: running the file by path puts its own directory on
sys.path, not the working directory holding the package.

    PYTHONPATH=. python tests/manual/geoid_url.py
"""
import sys
from urllib.parse import urlparse, parse_qs

from linkedin_jobs_scraper import LinkedinScraper
from linkedin_jobs_scraper.query import Query, QueryOptions, Location

build = LinkedinScraper._LinkedinScraper__build_search_url

failures = 0


def check(description: str, condition: bool) -> None:
    global failures
    status = 'PASS' if condition else 'FAIL'
    if not condition:
        failures += 1
    print('[%s] %s' % (status, description), flush=True)


query = Query(query='Software Engineer', options=QueryOptions())

# Case 1: plain string location -> location= present, no geoId
url = build(query, 'United States')
params = parse_qs(urlparse(url).query)
print('case 1 url:', url, flush=True)
check('string location sets location=United States', params.get('location') == ['United States'])
check('string location has no geoId', 'geoId' not in params)

# Case 2: Location with name -> geoId present, no location= param
loc = Location(geo_id='103644278', name='United States')
url = build(query, loc)
params = parse_qs(urlparse(url).query)
print('case 2 url:', url, flush=True)
check('Location sets geoId=103644278', params.get('geoId') == ['103644278'])
check('Location omits location= param', 'location' not in params)

# Case 3: Location without name -> geoId present, label falls back to geo_id
loc = Location(geo_id='103644278')
url = build(query, loc)
params = parse_qs(urlparse(url).query)
print('case 3 url:', url, flush=True)
check('nameless Location sets geoId=103644278', params.get('geoId') == ['103644278'])
check('nameless Location omits location= param', 'location' not in params)
check("nameless Location.label == '103644278'", Location(geo_id='103644278').label == '103644278')

print('\nTOTAL FAILURES:', failures, flush=True)
print('RESULT:', 'PASS' if failures == 0 else 'FAIL', flush=True)
sys.exit(1 if failures else 0)
