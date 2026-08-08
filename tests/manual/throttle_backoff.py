"""Check what a page of results is waited for, without asking LinkedIn for one.

Not collected by pytest (the filename does not match `test_*.py`), and it never touches the
live site: a local server hands out the HTTP 429 and the results list on demand, so both
behaviours can be driven instead of waited for.

Two things are under test. LinkedIn sends its 429 with an empty body, which Chrome throws
away in favour of its own error page; that page is on `chrome-error://chromewebdata/`, so
nothing about it names the cause - which is why the status is read from the navigation timing
entry, the one thing that survives the swap. And LinkedIn paints a preliminary results list
before the real one, which `__wait_for_stable_job_ids` has to decline to read.

    PYTHONPATH=. python -u tests/manual/throttle_backoff.py

The backoff delays are cut down for the run, so it takes seconds rather than a minute.
"""
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from time import time

from linkedin_jobs_scraper.strategies import authenticated_strategy as strat
from linkedin_jobs_scraper.utils.chrome_driver import build_driver

# The real ones are measured in tens of seconds, which is right for a run and wrong for a test
strat.THROTTLE_BACKOFF_DELAYS = (1, 2, 3)

PORT = 8732
PATH = '/jobs'


def results_page(count: int) -> bytes:
    """A results list holding `count` items, each with a rendered card."""

    items = ''.join(
        f'<li data-occludable-job-id="{i}"><div class="job-card-container">{i}</div></li>'
        for i in range(count))

    return f'<html><body><div class="scaffold-layout__list">{items}' \
           f'</div></body></html>'.encode()


# A page LinkedIn has finished with holds a full batch, which is what the settling wait
# requires before it believes a list that has stopped changing
FULL_PAGE = results_page(strat.PAGINATION_SIZE)
SHORT_PAGE = results_page(3)

state = {'throttle_for': 0, 'requests': 0, 'page': FULL_PAGE}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
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


class Scraper:
    """The only thing the strategy asks of its scraper here."""
    slow_mo = 0


failures = []


def check(label: str, got, expected) -> None:
    if got == expected:
        print(f'PASS  {label}')
        return

    print(f'FAIL  {label}: got {got!r}, expected {expected!r}')
    failures.append(label)


def main() -> int:
    server = HTTPServer(('127.0.0.1', PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    url = f'http://127.0.0.1:{PORT}{PATH}'
    strategy = strat.AuthenticatedStrategy(Scraper())
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
        started = time()
        check('the page loads', open_and_wait(strategy, driver, '[t]', url, wait), True)
        check('it is asked for once per refusal, then once more', state['requests'], 3)
        print(f'      {round(time() - started, 1)}s over delays {strat.THROTTLE_BACKOFF_DELAYS}')

        print('\n--- a throttle that outlasts the backoff gives up')
        state['throttle_for'], state['requests'], state['page'] = 99, 0, FULL_PAGE
        started = time()
        check('the page does not load', open_and_wait(strategy, driver, '[t]', url, wait), False)
        check('the backoff bounds the attempts',
              state['requests'], len(strat.THROTTLE_BACKOFF_DELAYS) + 1)
        check('the reply is read as throttled', is_throttled(driver), True)
        print(f'      {round(time() - started, 1)}s')

        print('\n--- a page that arrives but will not render is not waited on')
        state['throttle_for'], state['requests'], state['page'] = 0, 0, FULL_PAGE
        check('the page does not load', open_and_wait(strategy, driver, '[t]', url, lambda d: False), False)
        check('it is asked for once', state['requests'], 1)
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
