"""Ask LinkedIn what its responses carry, and ask BiDi what it costs to listen.

Not collected by pytest (the filename does not match `test_*.py`): it talks to the live site
with a real credential, and one of its parts deliberately provokes an HTTP 429, which spends
quota the account does not get back.

Two things are unknown and they decide whether the network layer is worth wiring into the
package at all. First, whether LinkedIn says how long to wait: the pacer's ladder of 5s, 15s
and 45s is invented, and `Retry-After` (RFC 6585 §4) would replace it with the server's own
number - but the Performance API the pacer reads today exposes only the status, never a
header, so the question cannot be asked from there. Second, whether normal responses carry a
quota budget (`X-RateLimit-*`), which would let a run be paced from what is left rather than
from what has already been refused.

The requests that actually get refused during a run are the ones LinkedIn's own JavaScript
makes, not ones this script could issue: a `fetch()` of our own is a different request from
the one that was refused, so it cannot answer the question about a 429's headers. BiDi is the
only instrument that sees those headers, which is why the probe measures with it - and, in
doing so, measures BiDi itself.

The measurement of the instrument matters as much as the measurement, because the two BiDi
routes are not equivalent:

    passive     `network.add_event_handler('response_started', ...)`, which installs no
                intercept and pauses nothing - but lives under `selenium.webdriver.common.bidi`,
                which Selenium documents as internal and reserves the right to change.
    intercept   `network.add_response_handler(...)`, the documented and supported API, which
                pauses every matching response and adds a websocket round trip to it.

So the supported route is the detectable one and the harmless one is unsupported, and this
project has already lost sessions to automation signals. Part C measures both rather than
choosing on preference.

Using the internal API here is deliberate and costs nothing: nothing in this file ships, so
there is no version to be broken by.

    PATH="/usr/bin:/bin" PYTHONPATH=. python -u tests/manual/network_headers_probe.py

Parts run in ascending order of cost and can be selected on the command line
(`... network_headers_probe.py a c`):

    a   the headers of a normal voyager response, read from the page that called it. One
        page load, no risk.
    c   what each of the two BiDi routes costs: events per page, threads, added page load
        time, and how many responses the documented intercept really pauses.
    b   the headers of a real 429, caught passively while a deliberately fast run provokes
        one. This is the part that spends the account's quota, so it runs last.

The profile is expected to hold a session already, so `LI_RM_COOKIE` / `LI_BCOOKIE` are not
needed. Chrome locks the profile directory, so each part builds and closes its own browser
and no two can run at once.

Environment:
    USER_DATA_DIR  profile to run with, default ~/.linkedin-jobs-scraper
    QUERY          search keywords, default 'Software Engineer'
    LOCATION       search location, default 'United Kingdom'
    LIMIT          jobs part b scrapes before giving up on provoking a 429, default 40
    ROUNDS         page loads per route in part c, default 2
    HEADLESS       0 to watch it, default 1
"""
import logging
import os
import sys
import threading
from pathlib import Path
from queue import Empty, Queue
from time import sleep, time
from urllib.parse import urlencode

from selenium.webdriver.common.bidi._network_handlers import globs_to_url_patterns
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from linkedin_jobs_scraper import LinkedinScraper, linkedin_scraper as scraper_module
from linkedin_jobs_scraper.events import Events, EventData, EventMetrics
from linkedin_jobs_scraper.query import Query, QueryOptions
from linkedin_jobs_scraper.strategies.authenticated_strategy import Selectors
from linkedin_jobs_scraper.utils.chrome_driver import (build_driver, get_default_driver_options,
                                                       mask_headless_user_agent,
                                                       resolve_masked_user_agent)
from linkedin_jobs_scraper.utils.constants import HOME_URL, JOBS_SEARCH_URL
from linkedin_jobs_scraper.utils.pacing import MIN_SLOW_MO

# Without a handler the package's own progress goes nowhere, and part b spends minutes with
# nothing to say for itself. Selenium and urllib3 are muted: they narrate every command.
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)-7s %(message)s')
logging.getLogger('urllib3').setLevel(logging.WARN)
logging.getLogger('selenium').setLevel(logging.WARN)

USER_DATA_DIR = os.environ.get('USER_DATA_DIR', str(Path.home() / '.linkedin-jobs-scraper'))
QUERY = os.environ.get('QUERY', 'Software Engineer')
LOCATION = os.environ.get('LOCATION', 'United Kingdom')
LIMIT = int(os.environ.get('LIMIT', '40'))
ROUNDS = int(os.environ.get('ROUNDS', '2'))
HEADLESS = os.environ.get('HEADLESS', '1') != '0'

THROTTLED_STATUS = 429

# LinkedIn's own API calls, which are same origin and therefore fully readable. Everything
# else a page asks for is a third party beacon as far as this run is concerned.
VOYAGER_MARKER = '/voyager/api/'

# Anything shaped like a quota, a wait, or a LinkedIn specific hint. Deliberately wide: the
# question is what exists, so a false positive costs a line of output and a false negative
# costs the answer.
QUOTA_HEADER_MARKERS = ('retry-after', 'ratelimit', 'rate-limit', 'x-li-', 'quota',
                        'throttl', 'x-restli', 'backoff', 'x-msedge-ref')

# How many distinct voyager endpoints part A asks again for. One endpoint answering with no
# quota header says nothing about the rest, and the jobs calls are the ones a run leans on.
ENDPOINT_SAMPLE_SIZE = 5
JOBS_ENDPOINT_MARKERS = ('job', 'search')

# The glob a Phase 2 intercept would want, and the fully qualified form of it. Both are put
# through Selenium's own translation, because what reaches the browser is not the glob.
INTERCEPT_GLOBS = ('**/voyager/api/**',
                   f'{HOME_URL}/voyager/api/**',
                   f'{HOME_URL}/**')

CONTAINER_TIMEOUT = 25

# What a page is asked for, once its own requests have had a chance to be made
SETTLE_AFTER_LOAD = 3

FETCH_HEADERS_SCRIPT = '''
    const callback = arguments[arguments.length - 1];
    const url = arguments[0];

    // Voyager refuses a call without the csrf token, and the token is the JSESSIONID value
    // with its quotes stripped
    const cookie = document.cookie.split('; ').find(c => c.startsWith('JSESSIONID='));
    const csrf = cookie ? cookie.slice('JSESSIONID='.length).replace(/"/g, '') : null;

    fetch(url, {credentials: 'include', headers: csrf ? {'csrf-token': csrf} : {}})
        .then(r => callback({status: r.status, headers: Array.from(r.headers.entries())}))
        .catch(e => callback({error: String(e)}));
'''

VOYAGER_URLS_SCRIPT = '''
    return performance.getEntriesByType('resource')
        .map(e => e.name)
        .filter(n => n.includes(arguments[0]));
'''


class CallbackErrors:
    """Count what fails on the BiDi callback threads, instead of printing every stack.

    Selenium reconciles an intercepted response on the thread the event arrived on, so a
    failure there never reaches the caller: it is printed by the threading module and the
    page is simply left waiting. Counting them by message is what makes the failure a
    measurement rather than noise.
    """

    def __init__(self):
        self.counts = {}
        self._lock = threading.Lock()
        self._previous = threading.excepthook

    def install(self) -> None:
        threading.excepthook = self._hook

    def restore(self) -> None:
        threading.excepthook = self._previous

    def _hook(self, args) -> None:
        message = f'{args.exc_type.__name__}: {str(args.exc_value)[:80]}'

        with self._lock:
            self.counts[message] = self.counts.get(message, 0) + 1

    def report(self, indent: str = '    ') -> None:
        with self._lock:
            if not self.counts:
                print(f'{indent}nothing failed on the callback threads')
                return

            for message, count in sorted(self.counts.items(), key=lambda item: -item[1]):
                print(f'{indent}{count} x {message}')


def sample_endpoints(urls: list) -> list:
    """Pick distinct voyager endpoints to ask again for, the jobs ones first.

    Distinct by path rather than by url: one endpoint called with sixty different query
    strings is one endpoint, and sampling it sixty times would measure nothing new.
    """

    by_path = {}

    for url in urls:
        by_path.setdefault(url.split('?')[0], url)

    ranked = sorted(by_path,
                    key=lambda path: any(marker in path.lower() for marker in JOBS_ENDPOINT_MARKERS),
                    reverse=True)

    return [by_path[path] for path in ranked[:ENDPOINT_SAMPLE_SIZE]]


def search_url(start: int = 0) -> str:
    """The results page a run opens, at a given offset."""

    return f'{JOBS_SEARCH_URL}?' + urlencode({'keywords': QUERY, 'location': LOCATION, 'start': start})


def header_markers(headers: dict) -> dict:
    """The headers worth reporting on their own, out of everything a response carried."""

    return {name: value for name, value in headers.items()
            if any(marker in name for marker in QUOTA_HEADER_MARKERS)}


def bidi_headers_to_dict(headers) -> dict:
    """Flatten the wire shape of BiDi headers, `[{name, value: {type, value}}]`."""

    flattened = {}

    for header in headers or []:
        value = header.get('value')

        if isinstance(value, dict):
            value = value.get('value')

        flattened[str(header.get('name', '')).lower()] = value

    return flattened


def print_headers(headers: dict, indent: str = '      ') -> None:
    """Print every header, then say which of them look like a quota."""

    for name in sorted(headers):
        print(f'{indent}{name}: {headers[name]}')

    interesting = header_markers(headers)

    if interesting:
        print(f'{indent}>>> of interest: {interesting}')
    else:
        print(f'{indent}>>> nothing quota shaped among {len(headers)} headers')


def build_probe_driver(bidi: bool = False):
    """A driver built the way the package builds its own, optionally speaking BiDi."""

    options = get_default_driver_options(
        headless=HEADLESS,
        user_data_dir=USER_DATA_DIR,
        user_agent=resolve_masked_user_agent() if HEADLESS else None)

    if bidi:
        # Not automatic: without the capability the first touch of `driver.network` raises
        # WebDriverException('Unable to find url to connect to from capabilities')
        options.enable_bidi = True

    driver = build_driver(options=options, timeout=30)
    driver.set_script_timeout(30)

    return driver


def prepare(driver) -> None:
    """Put the browser on LinkedIn and mask the headless token, as a run does."""

    driver.get(HOME_URL)
    mask_headless_user_agent(driver)


def open_results(driver, url: str) -> tuple[bool, float]:
    """Open a page of results and wait for its list, reporting how long it took."""

    started = time()

    try:
        driver.get(url)
        WebDriverWait(driver, CONTAINER_TIMEOUT).until(
            ec.presence_of_element_located((By.CSS_SELECTOR, Selectors.container)))
        rendered = True
    except BaseException:
        rendered = False

    return rendered, time() - started


class ResponseLog:
    """Everything the browser's own responses came back with, off the callback threads.

    A BiDi callback runs on a daemon thread of its own, one per event, so the only thing it
    is allowed to do is put on the queue. A single drainer turns the queue into numbers.
    """

    def __init__(self):
        self.queue = Queue()
        self.total = 0
        self.throttled = []
        self.peak_threads = 0
        self._stop = threading.Event()
        self._drainer = threading.Thread(target=self._drain, daemon=True)
        self._drainer.start()

    def on_response(self, params: dict) -> None:
        """The callback itself: one non-blocking operation and nothing else."""

        self.queue.put(params)

    def _drain(self) -> None:
        while not self._stop.is_set():
            try:
                params = self.queue.get(timeout=0.2)
            except Empty:
                continue

            self.total += 1
            self.peak_threads = max(self.peak_threads, threading.active_count())

            response = params.get('response') or {}

            if response.get('status') == THROTTLED_STATUS:
                self.throttled.append({
                    'url': response.get('url', ''),
                    'headers': bidi_headers_to_dict(response.get('headers')),
                    # Set only on a navigation, which is what tells a refused page apart
                    # from a refused fetch
                    'navigation': params.get('navigation'),
                })

    def settle(self, timeout: float = 5) -> None:
        """Let the queue empty before anything is read off the counters."""

        elapsed = 0

        while not self.queue.empty() and elapsed < timeout:
            sleep(0.1)
            elapsed += 0.1

    def stop(self) -> None:
        self._stop.set()


def part_a() -> None:
    """What a normal LinkedIn response carries."""

    print('\n=== A: the headers of a response nobody refused')
    driver = build_probe_driver()

    try:
        prepare(driver)
        rendered, elapsed = open_results(driver, search_url())
        print(f'    results page {"rendered" if rendered else "did not render"} in {round(elapsed, 1)}s')
        sleep(SETTLE_AFTER_LOAD)

        urls = driver.execute_script(VOYAGER_URLS_SCRIPT, VOYAGER_MARKER)
        print(f'    the page made {len(urls)} calls to {VOYAGER_MARKER}')

        if not urls:
            print('    nothing to ask again: the page made no voyager call this run')
            return

        targets = sample_endpoints(urls)
        print(f'    asking again for {len(targets)} distinct endpoints of them')

        for target in targets:
            print(f'\n    {target[:140]}')
            result = driver.execute_async_script(FETCH_HEADERS_SCRIPT, target)

            if not result or result.get('error'):
                print(f'      the fetch failed: {result and result.get("error")}')
                continue

            headers = {name.lower(): value for name, value in result.get('headers') or []}
            print(f'      HTTP {result.get("status")}, {len(headers)} headers readable (same origin)')
            print_headers(headers)
    finally:
        driver.quit()


def part_c() -> None:
    """What each of the two routes costs, measured rather than assumed."""

    print('\n=== C: what listening costs')

    print('\n--- what the documented intercept really asks the browser to pause')
    print('    Selenium sends only the literal components of a glob and re-filters in Python,')
    print('    so the browser side pattern can be far wider than the glob reads:')

    for glob in INTERCEPT_GLOBS:
        translated = globs_to_url_patterns([glob])
        print(f'    {glob:44} -> {translated if translated is not None else "None (no filter: every request)"}')

    print('\n--- a page load with nothing listening')
    driver = build_probe_driver()
    plain = []

    try:
        prepare(driver)

        for i in range(ROUNDS):
            rendered, elapsed = open_results(driver, search_url(i * 25))
            plain.append(elapsed)
            print(f'    round {i + 1}: {"rendered" if rendered else "did not render"} in {round(elapsed, 2)}s')
    finally:
        driver.quit()

    print('\n--- a page load with the passive subscription (internal API)')
    driver = build_probe_driver(bidi=True)
    log = ResponseLog()
    passive = []
    per_page = []

    try:
        driver.network.add_event_handler('response_started', log.on_response)
        prepare(driver)

        for i in range(ROUNDS):
            before = log.total
            rendered, elapsed = open_results(driver, search_url(i * 25))
            sleep(SETTLE_AFTER_LOAD)
            log.settle()
            passive.append(elapsed)
            per_page.append(log.total - before)
            print(f'    round {i + 1}: {"rendered" if rendered else "did not render"} in '
                  f'{round(elapsed, 2)}s, {log.total - before} responses seen')
    except BaseException as e:
        print(f'    the passive route failed: {type(e).__name__}: {e}')
    finally:
        log.stop()
        driver.quit()

    print(f'    {log.total} events in all, one ephemeral thread each; '
          f'{max(per_page or [0])} on the busiest page, peak live threads {log.peak_threads}')

    print('\n--- a page load with the documented intercept')
    driver = build_probe_driver(bidi=True)
    errors = CallbackErrors()
    errors.install()
    intercepted = []
    paused = {'total': 0, 'voyager': 0}
    lock = threading.Lock()

    def on_intercepted(response) -> None:
        with lock:
            paused['total'] += 1

            if VOYAGER_MARKER in (response.url or ''):
                paused['voyager'] += 1

    try:
        driver.network.add_response_handler([INTERCEPT_GLOBS[0]], on_intercepted)
        prepare(driver)

        for i in range(ROUNDS):
            rendered, elapsed = open_results(driver, search_url(i * 25))
            sleep(SETTLE_AFTER_LOAD)
            intercepted.append(elapsed)
            print(f'    round {i + 1}: {"rendered" if rendered else "did not render"} in '
                  f'{round(elapsed, 2)}s, {paused["total"]} responses paused so far')
    except BaseException as e:
        print(f'    the intercept route failed: {type(e).__name__}: {e}')
    finally:
        print('    what failed while reconciling the paused responses:')
        errors.report('      ')
        errors.restore()

        try:
            driver.quit()
        except BaseException as e:
            print(f'    even closing the browser failed: {type(e).__name__}')

    def mean(values: list) -> float:
        return round(sum(values) / len(values), 2) if values else 0.0

    print(f'\n    mean page load: {mean(plain)}s with nothing listening, '
          f'{mean(passive)}s passive, {mean(intercepted)}s intercepted')
    print(f'    the intercept paused {paused["total"]} responses to reach the '
          f'{paused["voyager"]} that match {INTERCEPT_GLOBS[0]}')


def part_b() -> None:
    """The headers of a real 429, which only the browser's own requests can produce."""

    print('\n=== B: the headers of a refusal')
    print(f'    running {LIMIT} jobs at slow_mo={MIN_SLOW_MO} with adaptive pacing off, to provoke one')

    log = ResponseLog()
    original_build_driver = scraper_module.build_driver

    def build_driver_with_bidi(**kwargs):
        options = get_default_driver_options(
            headless=kwargs.get('headless', True),
            user_data_dir=kwargs.get('user_data_dir'),
            user_agent=resolve_masked_user_agent(kwargs.get('executable_path'),
                                                 kwargs.get('binary_location'))
            if kwargs.get('headless', True) else None)
        options.enable_bidi = True

        driver = original_build_driver(**{**kwargs, 'options': options})
        driver.network.add_event_handler('response_started', log.on_response)

        return driver

    scraper_module.build_driver = build_driver_with_bidi

    processed = []
    metrics_seen = []

    scraper = LinkedinScraper(
        headless=HEADLESS,
        max_workers=1,
        # The adaptation is what a run wants and what a measurement does not: it would slow
        # the run down before the refusal it is here to catch
        slow_mo=MIN_SLOW_MO,
        adaptive_slow_mo=False,
        page_load_timeout=40,
        user_data_dir=USER_DATA_DIR)

    scraper.on(Events.DATA, lambda data: processed.append(data.job_id))
    scraper.on(Events.METRICS, lambda metrics: metrics_seen.append(str(metrics)))
    scraper.on(Events.ERROR, lambda err: print(f'    ERROR {str(err)[:200]}'))
    scraper.on(Events.END, lambda: None)

    try:
        scraper.run(Query(query=QUERY,
                          options=QueryOptions(locations=[LOCATION], limit=LIMIT, apply_link=False)))
    except BaseException as e:
        print(f'    the run ended early: {type(e).__name__}: {e}')
    finally:
        scraper_module.build_driver = original_build_driver
        log.settle()
        log.stop()

    print(f'\n    {len(processed)} jobs delivered, {log.total} responses seen')

    for metrics in metrics_seen:
        print(f'    metrics: {metrics}')

    if not log.throttled:
        print(f'    no {THROTTLED_STATUS} was provoked, so nothing can be said about its headers. '
              f'Raise LIMIT, or run it again on a less rested address.')
        return

    navigations = [r for r in log.throttled if r['navigation']]
    voyager = [r for r in log.throttled if VOYAGER_MARKER in r['url']]

    print(f'\n    {len(log.throttled)} refusals: {len(navigations)} on a navigation, '
          f'{len(log.throttled) - len(navigations)} on a request the page made')
    print(f'    {len(voyager)} of them are {VOYAGER_MARKER} calls and '
          f'{len(log.throttled) - len(voyager)} are something else - which is the noise ratio '
          f'`__count_throttled_resources` weighs equally today')

    seen_urls = set()

    for refusal in log.throttled:
        url = refusal['url']

        if url in seen_urls:
            continue

        seen_urls.add(url)
        kind = 'navigation' if refusal['navigation'] else 'page request'
        print(f'\n    [{kind}] {url[:140]}')
        print_headers(refusal['headers'])


PARTS = {'a': part_a, 'b': part_b, 'c': part_c}


def main() -> int:
    requested = [arg.lower() for arg in sys.argv[1:]] or ['a', 'c', 'b']
    unknown = [name for name in requested if name not in PARTS]

    if unknown:
        print(f'Unknown parts {unknown}, expected any of {sorted(PARTS)}')
        return 2

    print(f'profile   {USER_DATA_DIR}')
    print(f'query     {QUERY!r} in {LOCATION!r}')
    print(f'parts     {requested}')

    if not Path(USER_DATA_DIR).exists():
        print(f'\nThe profile does not exist. Sign in once with '
              f'python -m linkedin_jobs_scraper.login --user-data-dir {USER_DATA_DIR}')
        return 2

    # Ascending cost, whatever order they were asked for in: b spends quota the account does
    # not get back, so everything cheaper is measured before it
    for name in ('a', 'c', 'b'):
        if name in requested:
            PARTS[name]()

    return 0


if __name__ == '__main__':
    sys.exit(main())
