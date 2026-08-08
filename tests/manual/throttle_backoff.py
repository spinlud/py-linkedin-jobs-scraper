"""Check what a page of results is waited for and how a run paces itself, without asking
LinkedIn for either.

Not collected by pytest (the filename does not match `test_*.py`), and it never touches the
live site: a local server hands out the HTTP 429 and the results list on demand, so every
behaviour here can be driven instead of waited for.

Three things are under test. LinkedIn sends its 429 with an empty body, which Chrome throws
away in favour of its own error page; that page is on `chrome-error://chromewebdata/`, so
nothing about it names the cause - which is why the status is read from the navigation timing
entry, the one thing that survives the swap. LinkedIn paints a preliminary results list
before the real one, which `__wait_for_stable_job_ids` has to decline to read. And a run
paces itself from both kinds of refusal, the navigation and the fetches a page makes on its
own, which is the only place a throttled job detail is visible at all.

    PYTHONPATH=. python -u tests/manual/throttle_backoff.py

The backoff delays are cut down for the run, so it takes seconds rather than a minute.
"""
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from time import sleep, time

from linkedin_jobs_scraper import LinkedinScraper
from linkedin_jobs_scraper.strategies import authenticated_strategy as strat
from linkedin_jobs_scraper.utils.chrome_driver import build_driver
from linkedin_jobs_scraper.utils.pacing import (CLEAN_RUN_BEFORE_EASING, MIN_SLOW_MO,
                                                PACING_EASE_FACTOR, Pacer)

# The real ones are measured in tens of seconds, which is right for a run and wrong for a test
strat.THROTTLE_BACKOFF_DELAYS = (1, 2, 3)

PORT = 8732
PATH = '/jobs'

# Two resources a page can ask for, one of which is always refused
THROTTLED_PATH = '/throttled'
SERVED_PATH = '/served'


def results_page(count: int, fetches: tuple = ()) -> bytes:
    """A results list holding `count` items, each with a rendered card.

    `fetches` are paths the page asks for on its own, the way LinkedIn fetches job details.
    """

    items = ''.join(
        f'<li data-occludable-job-id="{i}"><div class="job-card-container">{i}</div></li>'
        for i in range(count))

    script = ''.join(f'fetch("{path}").catch(() => {{}});' for path in fetches)

    return f'<html><body><div class="scaffold-layout__list">{items}</div>' \
           f'<script>{script}</script></body></html>'.encode()


# A page LinkedIn has finished with holds a full batch, which is what the settling wait
# requires before it believes a list that has stopped changing
FULL_PAGE = results_page(strat.PAGINATION_SIZE)
SHORT_PAGE = results_page(3)
FETCHING_PAGE = results_page(strat.PAGINATION_SIZE, (THROTTLED_PATH, SERVED_PATH))

state = {'throttle_for': 0, 'requests': 0, 'page': FULL_PAGE}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # The two resources answer for themselves, so a page can be refused a fetch while
        # being served perfectly well itself
        if self.path == THROTTLED_PATH:
            self.send_response(429)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return

        if self.path == SERVED_PATH:
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'ok')
            return

        # Chrome asks for the favicon of every page it renders, which is not an attempt
        if self.path == PATH:
            state['requests'] += 1

        if state['throttle_for'] > 0:
            state['throttle_for'] -= 1
            self.send_response(429)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return

        page = state['page']
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def log_message(self, *args):
        pass


open_and_wait = strat.AuthenticatedStrategy._AuthenticatedStrategy__open_and_wait
is_throttled = strat.AuthenticatedStrategy._AuthenticatedStrategy__is_throttled
wait_for_container = strat.AuthenticatedStrategy._AuthenticatedStrategy__wait_for_container
wait_for_stable_job_ids = strat.AuthenticatedStrategy._AuthenticatedStrategy__wait_for_stable_job_ids
count_throttled_resources = strat.AuthenticatedStrategy._AuthenticatedStrategy__count_throttled_resources
observe_resources = strat.AuthenticatedStrategy._AuthenticatedStrategy__observe_resources


class Scraper:
    """The only thing the strategy asks of its scraper here."""

    def __init__(self):
        # Fast enough not to pad the run, with enough room above it for a rise to show
        self.pacer = Pacer(floor=0.01, ceiling=10)


failures = []


def check(label: str, got, expected) -> None:
    if got == expected:
        print(f'PASS  {label}')
        return

    print(f'FAIL  {label}: got {got!r}, expected {expected!r}')
    failures.append(label)


def raises_value_error(**kwargs) -> bool:
    """Whether the scraper refuses a set of constructor arguments."""

    try:
        scraper = LinkedinScraper(**kwargs)
    except ValueError:
        return True

    scraper._pool.shutdown(wait=False)
    return False


class FakeDriver:
    """A driver answering the resource reading with whatever it has been told to.

    The three way comparison in `__observe_resources` turns on which document a reading came
    from, and a browser cannot be asked for a chosen time origin.
    """

    def __init__(self):
        self.reading = [0.0, 0]

    def execute_script(self, script, *args):
        return list(self.reading)


def wait_for_throttled_resources(driver, expected: int, timeout=5) -> int | None:
    """Poll the resource buffer until the page's own fetches have landed."""

    elapsed = 0

    while elapsed < timeout:
        reading = count_throttled_resources(driver)

        if reading and reading[1] == expected:
            return reading[1]

        sleep(0.1)
        elapsed += 0.1

    reading = count_throttled_resources(driver)

    return reading[1] if reading else None


def check_pacer() -> None:
    """The pacer on its own, with no browser and no server."""

    print('\n--- a pacer rises on refusals, up to its ceiling')
    pacer = Pacer(floor=0.5, ceiling=5)
    check('the first refusal doubles the pace', pacer.throttled(), 1)
    check('and the next one doubles it again', pacer.throttled(), 2)

    for _ in range(10):
        pacer.throttled()

    check('it stops at the ceiling', pacer.delay, 5)
    check('every refusal is counted', pacer.throttled_count, 12)

    print('\n--- easing has to be earned, and stops at the floor')
    pacer = Pacer(floor=0.5, ceiling=5)
    pacer.throttled()
    pacer.throttled()

    for _ in range(CLEAN_RUN_BEFORE_EASING - 1):
        pacer.clean()

    check('a partial run of clean work changes nothing', pacer.delay, 2)
    check('completing it eases the pace', round(pacer.clean(), 4), round(2 / PACING_EASE_FACTOR, 4))

    for _ in range(CLEAN_RUN_BEFORE_EASING * 20):
        pacer.clean()

    check('it never eases below the floor', pacer.delay, 0.5)

    print('\n--- a refusal resets the run of clean work')
    pacer = Pacer(floor=0.5, ceiling=5)
    pacer.throttled()

    for _ in range(CLEAN_RUN_BEFORE_EASING - 1):
        pacer.clean()

    pacer.throttled()

    for _ in range(CLEAN_RUN_BEFORE_EASING - 1):
        pacer.clean()

    check('the interrupted run does not carry over', pacer.delay, 2)

    print('\n--- a pacer whose ceiling is its floor is inert')
    inert = Pacer(floor=0.5, ceiling=0.5)
    inert.throttled()
    inert.throttled()
    check('the pace does not move', inert.delay, 0.5)
    check('but the refusals are still counted', inert.throttled_count, 2)

    print('\n--- concurrent reports leave a consistent pace')
    shared = Pacer(floor=0.5, ceiling=5)
    threads = [threading.Thread(target=lambda: [shared.throttled() for _ in range(50)])
               for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    check('no report is lost', shared.throttled_count, 400)
    check('the pace is exactly the ceiling', shared.delay, 5)


def check_jitter() -> None:
    """A backoff wait keeps the shape of its ladder without keeping its exact value."""

    print('\n--- a backoff wait is drawn around its step')
    base = 10
    draws = [strat.jittered_backoff(base) for _ in range(500)]

    check('every wait stays within half a step of it',
          all(base * (1 - strat.THROTTLE_BACKOFF_JITTER) <= d <= base * (1 + strat.THROTTLE_BACKOFF_JITTER)
              for d in draws),
          True)
    check('and two workers do not draw the same wait', len(set(draws)) > 1, True)


def check_document_token() -> None:
    """A reading only means something against another from the same document."""

    scraper = Scraper()
    strategy = strat.AuthenticatedStrategy(scraper)
    driver = FakeDriver()

    print('\n--- refusals are counted within one document')
    scraper.pacer = Pacer(floor=0.5, ceiling=5)
    driver.reading = [1000.0, 0]
    baseline = observe_resources(strategy, driver, '[t]', None)
    check('the first reading is a baseline and nothing else', baseline, (1000.0, 0))
    check('so it reports nothing', scraper.pacer.throttled_count, 0)

    driver.reading = [1000.0, 2]
    baseline = observe_resources(strategy, driver, '[t]', baseline)
    check('the same document with more refusals raises the pace', scraper.pacer.throttled_count, 1)
    check('and the reading names the document it came from', baseline, (1000.0, 2))

    print('\n--- a new document re-baselines even when its count matches')
    scraper.pacer = Pacer(floor=0.5, ceiling=5)
    scraper.pacer.throttled()
    baseline = (1000.0, 0)

    for i in range(CLEAN_RUN_BEFORE_EASING):
        driver.reading = [2000.0 + i, 0]
        baseline = observe_resources(strategy, driver, '[t]', baseline)

    check('a document swap is never a clean tick, whatever it counts', scraper.pacer.delay, 1)
    check('it only moves the baseline', baseline, (2000.0 + CLEAN_RUN_BEFORE_EASING - 1, 0))

    print('\n--- the same document refused nothing new is clean work')
    scraper.pacer = Pacer(floor=0.5, ceiling=5)
    scraper.pacer.throttled()
    driver.reading = [3000.0, 1]
    baseline = observe_resources(strategy, driver, '[t]', None)

    for _ in range(CLEAN_RUN_BEFORE_EASING):
        baseline = observe_resources(strategy, driver, '[t]', baseline)

    check('a run of them eases the pace', round(scraper.pacer.delay, 4), round(1 / PACING_EASE_FACTOR, 4))
    check('and nothing was read as a refusal', scraper.pacer.throttled_count, 1)


def check_validation() -> None:
    """slow_mo is a floor a caller cannot ask below."""

    print(f'\n--- slow_mo below {MIN_SLOW_MO} is refused')
    check('slow_mo=0 is refused', raises_value_error(slow_mo=0), True)
    check('slow_mo=0.1 is refused', raises_value_error(slow_mo=0.1), True)
    check('adaptive_slow_mo must be a bool',
          raises_value_error(slow_mo=0.5, adaptive_slow_mo='yes'), True)

    scraper = LinkedinScraper(slow_mo=MIN_SLOW_MO)

    try:
        check(f'slow_mo={MIN_SLOW_MO} is accepted', scraper.slow_mo, MIN_SLOW_MO)

        for _ in range(20):
            scraper.pacer.throttled()

        check('and yields a ceiling of 2', scraper.pacer.delay, 2)
    finally:
        scraper._pool.shutdown(wait=False)

    opted_out = LinkedinScraper(slow_mo=0.5, adaptive_slow_mo=False)

    try:
        opted_out.pacer.throttled()
        check('opting out leaves the pace where the caller put it', opted_out.pacer.delay, 0.5)
    finally:
        opted_out._pool.shutdown(wait=False)


def main() -> int:
    check_pacer()
    check_jitter()
    check_document_token()
    check_validation()

    server = HTTPServer(('127.0.0.1', PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    url = f'http://127.0.0.1:{PORT}{PATH}'
    scraper = Scraper()
    strategy = strat.AuthenticatedStrategy(scraper)
    driver = build_driver(headless=True, timeout=20)

    # A short container wait: every attempt at a throttled page spends the whole of it
    def wait(d):
        return wait_for_container(d, 2)

    try:
        print('\n--- a page that is served is not retried')
        state['throttle_for'], state['requests'], state['page'] = 0, 0, FULL_PAGE
        started = time()
        check('the page loads', open_and_wait(strategy, driver, '[t]', url, wait), True)
        check('it is asked for once', state['requests'], 1)
        check('it is not read as throttled', is_throttled(driver), False)
        check('and the pace was left alone', scraper.pacer.throttled_count, 0)
        print(f'      {round(time() - started, 1)}s')

        print('\n--- a full batch that has stopped changing is read straight away')
        started = time()
        settled = wait_for_stable_job_ids(driver, 8, 0.5)
        elapsed = time() - started
        check('every item is reported', len(settled), strat.PAGINATION_SIZE)
        check('it does not wait the timeout out', elapsed < 3, True)
        print(f'      {round(elapsed, 1)}s')

        print('\n--- a list short of a full batch is only believed once the wait runs out')
        state['page'] = SHORT_PAGE
        open_and_wait(strategy, driver, '[t]', url, wait)
        started = time()
        settled = wait_for_stable_job_ids(driver, 3, 0.5)
        elapsed = time() - started
        check('the short list is still reported', len(settled), 3)
        check('it costs the timeout', elapsed >= 3, True)
        print(f'      {round(elapsed, 1)}s')

        print('\n--- a throttle that ends is waited out')
        state['throttle_for'], state['requests'], state['page'] = 2, 0, FULL_PAGE
        scraper.pacer = Pacer(floor=0.01, ceiling=10)
        started = time()
        check('the page loads', open_and_wait(strategy, driver, '[t]', url, wait), True)
        check('it is asked for once per refusal, then once more', state['requests'], 3)
        check('the pace rose once per refusal', scraper.pacer.throttled_count, 2)
        check('which doubled it twice', round(scraper.pacer.delay, 4), 0.04)
        print(f'      {round(time() - started, 1)}s over delays {strat.THROTTLE_BACKOFF_DELAYS}')

        print('\n--- a throttle that outlasts the backoff gives up')
        state['throttle_for'], state['requests'], state['page'] = 99, 0, FULL_PAGE
        scraper.pacer = Pacer(floor=0.01, ceiling=10)
        started = time()
        check('the page does not load', open_and_wait(strategy, driver, '[t]', url, wait), False)
        check('the backoff bounds the attempts',
              state['requests'], len(strat.THROTTLE_BACKOFF_DELAYS) + 1)
        check('the reply is read as throttled', is_throttled(driver), True)
        check('every attempt raised the pace',
              scraper.pacer.throttled_count, len(strat.THROTTLE_BACKOFF_DELAYS) + 1)
        print(f'      {round(time() - started, 1)}s')

        print('\n--- a page that arrives but will not render is not waited on')
        state['throttle_for'], state['requests'], state['page'] = 0, 0, FULL_PAGE
        check('the page does not load', open_and_wait(strategy, driver, '[t]', url, lambda d: False), False)
        check('it is asked for once', state['requests'], 1)

        print('\n--- a refused fetch is read off the page that made it')
        state['throttle_for'], state['requests'], state['page'] = 0, 0, FETCHING_PAGE
        scraper.pacer = Pacer(floor=0.01, ceiling=10)
        check('the page itself loads fine', open_and_wait(strategy, driver, '[t]', url, wait), True)
        check('the refused fetch is counted, the served one is not',
              wait_for_throttled_resources(driver, 1), 1)

        # The fetches have already landed, so the baseline is this same document taken
        # before them
        origin = count_throttled_resources(driver)[0]

        baseline = observe_resources(strategy, driver, '[t]', (origin, 0))
        check('the delta raises the pace', scraper.pacer.throttled_count, 1)
        check('and becomes what the next reading compares against', baseline, (origin, 1))

        baseline = observe_resources(strategy, driver, '[t]', baseline)
        check('reading the same buffer again reports nothing new',
              scraper.pacer.throttled_count, 1)
        check('the baseline holds', baseline, (origin, 1))

        print('\n--- a new document re-baselines instead of counting')
        state['page'] = FULL_PAGE
        check('the next page loads', open_and_wait(strategy, driver, '[t]', url, wait), True)
        baseline = observe_resources(strategy, driver, '[t]', baseline)
        check('the emptied buffer is the new baseline', baseline[1], 0)
        check('and a real navigation does give a new time origin', baseline[0] != origin, True)
        check('and the drop is not read as a refusal', scraper.pacer.throttled_count, 1)
    finally:
        try:
            driver.quit()
        except BaseException:
            pass
        server.shutdown()

    if failures:
        print(f'\nFAILED: {failures}')
        return 1

    print('\nAll checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
