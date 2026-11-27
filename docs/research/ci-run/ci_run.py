# ruff: noqa: BLE001, C901, E402, E741, PLC0415, PLW1510, RUF100, T201
# Throwaway research harness, outside the package
"""
One CI run: sign in from the remember-me pair on a GitHub runner, then one real search.

Usage: python ci_run.py <stack>
  stack: selenium | patchright | pydoll-pw

The pair comes from LI_RM_COOKIE and LI_BCOOKIE. The browser starts on an empty profile.
Selenium is the package itself (LinkedinScraper.run, limit 5), which signs in from the pair
on its own. The candidates follow the package's sequence by hand:
  1. home page, then the User-Agent override;
  2. inject the pair, open the feed and follow the sign-in for up to 60 s;
  3. without a session, open the feed once more and follow it for 30 s;
  4. with one, search and open the first five jobs.

The log is public: it holds paths, query parameter names, titles, HTTP statuses, iframe
hosts, cookie names, counts and lengths. No cookie value, no URL value, no page text.
This reaches LinkedIn: run it only when the user asks.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'offline-fingerprint-rung'))
from rung import CANDIDATE_ARGS, CHROME, HINTS, masked_user_agent, ua_override_params  # noqa: E402

QUERY, GEO_ID, LOCATION = 'python', '103350119', 'Italy'
HOME = 'https://www.linkedin.com'
FEED = 'https://www.linkedin.com/feed/'
SEARCH = 'https://www.linkedin.com/jobs/search-results/?' + urlencode(
    {'keywords': QUERY, 'geoId': GEO_ID}
)
CARD_PREFIX = 'job-card-component-ref-'
SIGN_IN_PATHS = ('/uas/login', '/login', '/checkpoint/lg/login', '/authwall')
LIMIT = 5
SLOW_MO = 0.8
YEAR = 365 * 24 * 60 * 60

STATE = """(() => {
  const nav = performance.getEntriesByType('navigation')[0];
  return {
    path: location.pathname,
    params: Array.from(new URLSearchParams(location.search).keys()),
    title: document.title,
    ready: document.readyState,
    status: nav ? nav.responseStatus : null,
    redirects: nav ? nav.redirectCount : null,
    iframes: Array.from(new Set(Array.from(document.querySelectorAll('iframe[src]'))
      .map(f => { try { return new URL(f.src).host; } catch (e) { return '?'; } }))),
    cards: Array.from(document.querySelectorAll('[componentkey^="job-card-component-ref-"]'))
      .map(e => e.getAttribute('componentkey').slice(23)),
    webdriver: navigator.webdriver,
    headless_ua: navigator.userAgent.includes('Headless'),
  };
})()"""


def flag(s: dict[str, Any], cookie_names: list[str]) -> str | None:
    if s['title'].startswith('Just a moment'):
        return 'cloudflare'
    if 'chp_token' in cookie_names or any('google.com' in h for h in s['iframes']):
        return 'recaptcha'
    if s['path'].startswith('/checkpoint/challenge'):
        return 'checkpoint'
    if any(s['path'].startswith(p) for p in SIGN_IN_PATHS):
        return 'sign-in'
    return None


def runner_network() -> str:
    # The runner's network operator only, never its address
    try:
        out = subprocess.run(
            ['curl', '-s', '--max-time', '5', 'https://ipinfo.io/org'],
            capture_output=True,
            text=True,
        ).stdout.strip()
        return out.split(' ', 1)[1] if ' ' in out else out
    except Exception:
        return '?'


def run_selenium(out: dict[str, Any]) -> None:
    import logging

    from linkedin_jobs_scraper import LinkedinScraper
    from linkedin_jobs_scraper.events import Events
    from linkedin_jobs_scraper.query import Location, Query, QueryOptions

    logging.basicConfig(level=logging.INFO)
    scraper = LinkedinScraper(headless=True, max_workers=1, slow_mo=SLOW_MO)
    out['jobs'], out['errors'], out['events'] = [], [], []
    scraper.on(
        Events.DATA,
        lambda d: out['jobs'].append({'id': d.job_id, 'description_len': len(d.description or '')}),
    )
    scraper.on(Events.ERROR, lambda e: out['errors'].append(type(e).__name__))
    scraper.on(Events.INVALID_SESSION, lambda: out['events'].append('invalid_session'))
    scraper.on(Events.END, lambda: out['events'].append('end'))
    scraper.run(
        [
            Query(
                query=QUERY,
                options=QueryOptions(
                    locations=[Location(geo_id=GEO_ID, name=LOCATION)], limit=LIMIT
                ),
            )
        ]
    )
    out['session'] = 'invalid_session' not in out['events']


async def run_candidate(stack: str, out: dict[str, Any]) -> None:
    if stack == 'patchright':
        from patchright.async_api import async_playwright
    else:
        from pydoll.playwright.async_api import async_playwright

    li_rm, bcookie = os.environ['LI_RM_COOKIE'], os.environ['LI_BCOOKIE']
    work = Path(tempfile.mkdtemp(prefix='ci-run-'))
    profile = str(work / 'profile')
    ua = masked_user_agent()
    args = [*CANDIDATE_ARGS, f'--user-agent={ua}']
    kw: dict[str, Any] = {}
    pw = await async_playwright().start()
    if stack == 'patchright':
        # Keep third-party storage partitioning on: drop it from Patchright's default flag
        probe = await pw.chromium.launch_persistent_context(
            str(work / 'probe-profile'), channel='chrome', headless=True
        )
        ps = subprocess.run(['ps', 'axww', '-o', 'args'], capture_output=True, text=True).stdout
        line = next(
            l for l in ps.splitlines() if 'probe-profile' in l and '--disable-features=' in l
        )
        default = next(a for a in line.split(' ') if a.startswith('--disable-features='))
        await probe.close()
        kept = ','.join(
            f for f in default.split('=', 1)[1].split(',') if f != 'ThirdPartyStoragePartitioning'
        )
        args.append(f'--disable-features={kept}')
        kw = {'channel': 'chrome', 'ignore_default_args': [default]}
    else:
        kw = {'executable_path': CHROME}
    ctx = await pw.chromium.launch_persistent_context(
        profile, headless=True, no_viewport=True, args=args, **kw
    )
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()

    async def ev(expr: str) -> Any:
        if stack == 'patchright':
            return await page.evaluate(expr, isolated_context=True)
        return await page.evaluate(expr)

    async def cdp(method: str, params: dict[str, Any]) -> None:
        if stack == 'patchright':
            s = await ctx.new_cdp_session(page)
            await s.send(method, params)
        else:
            await page.tab.execute_command({'method': method, 'params': params})

    async def cookie_names() -> list[str]:
        try:
            return sorted({c['name'] for c in await ctx.cookies(HOME)})
        except Exception as e:
            return [f'unreadable: {type(e).__name__}']

    async def snapshot() -> dict[str, Any]:
        try:
            s = await ev(STATE)
        except Exception as e:
            s = {
                'path': '?',
                'params': [],
                'title': '',
                'iframes': [],
                'cards': [],
                'eval_error': type(e).__name__,
            }
        names = await cookie_names()
        s['flag'] = flag(s, names)
        s['cookies'] = names
        s['li_at'] = 'li_at' in names
        s['t'] = round(time.time() - t0, 1)
        return s

    def record(tag: str, s: dict[str, Any]) -> None:
        out['states'].append(
            {'tag': tag, **{k: v for k, v in s.items() if k != 'cards'}, 'n_cards': len(s['cards'])}
        )

    async def follow(tag: str, seconds: int) -> bool:
        last = None
        end = time.time() + seconds
        while time.time() < end:
            await asyncio.sleep(1)
            s = await snapshot()
            key = (
                s['path'],
                s['title'],
                s.get('ready'),
                s['flag'],
                tuple(s['iframes']),
                tuple(s['cookies']),
            )
            if key != last:
                record(tag, s)
                last = key
            if s['li_at'] and not s['flag']:
                return True
        record(f'{tag}-end', await snapshot())
        return False

    t0 = time.time()
    out['states'], out['jobs'] = [], []
    try:
        await page.goto(HOME, wait_until='commit', timeout=60000)
        await asyncio.sleep(SLOW_MO + 3)
        raw = await ev(HINTS)
        await cdp('Network.setUserAgentOverride', ua_override_params(raw, ua))
        out['ua_override'] = True
        record('home', await snapshot())
        expires = int(time.time()) + YEAR
        await ctx.add_cookies(
            [
                {
                    'name': 'li_rm',
                    'value': li_rm,
                    'domain': '.www.linkedin.com',
                    'path': '/',
                    'expires': expires,
                    'secure': True,
                    'httpOnly': True,
                    'sameSite': 'None',
                },
                {
                    'name': 'bcookie',
                    'value': bcookie,
                    'domain': '.linkedin.com',
                    'path': '/',
                    'expires': expires,
                    'secure': True,
                    'sameSite': 'None',
                },
            ]
        )
        await page.goto(FEED, wait_until='commit', timeout=60000)
        out['session'] = await follow('sign-in', 60)
        if not out['session']:
            await page.goto(FEED, wait_until='commit', timeout=60000)
            out['session'] = await follow('sign-in-retry', 30)
        if not out['session']:
            return
        await asyncio.sleep(SLOW_MO + 2)
        await page.goto(SEARCH, wait_until='commit', timeout=60000)
        s: dict[str, Any] = {}
        for _ in range(30):
            await asyncio.sleep(1)
            s = await snapshot()
            if s['cards'] or s['flag']:
                break
        record('search', s)
        if s['flag']:
            return
        for job_id in list(dict.fromkeys(s['cards']))[:LIMIT]:
            await asyncio.sleep(SLOW_MO)
            await page.locator(f'[role="button"][componentkey="{CARD_PREFIX}{job_id}"]').click()
            about = page.locator(f'[componentkey="JobDetails_AboutTheJob_{job_id}"]')
            text = ''
            try:
                await about.wait_for(timeout=20000)
                for _ in range(20):
                    text = (await about.inner_text()).strip()
                    if text:
                        break
                    await asyncio.sleep(0.5)
            except Exception as e:
                out.setdefault('job_errors', []).append(f'{job_id}: {type(e).__name__}')
            out['jobs'].append({'id': job_id, 'description_len': len(text)})
        record('after-jobs', await snapshot())
    finally:
        out['elapsed'] = round(time.time() - t0, 1)
        await ctx.close()
        await pw.stop()


def main() -> None:
    stack = sys.argv[1]
    out: dict[str, Any] = {
        'stack': stack,
        'runner_network': runner_network(),
        'query': QUERY,
        'location': LOCATION,
    }
    try:
        if stack == 'selenium':
            run_selenium(out)
        else:
            asyncio.run(run_candidate(stack, out))
    except Exception as e:
        out['error'] = type(e).__name__
    print('RESULT ' + json.dumps(out, ensure_ascii=False))


if __name__ == '__main__':
    main()
