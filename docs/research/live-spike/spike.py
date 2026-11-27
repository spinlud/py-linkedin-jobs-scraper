# ruff: noqa  throwaway research harness, outside the package
"""
Live local spike: one real LinkedIn search with one stack on the signed-in profile.

Usage: python spike.py <stack> <out_dir>
  stack: selenium | patchright | pydoll-pw

Selenium is the package itself (LinkedinScraper.run, limit 5). The candidates follow the
package's sequence by hand: home page, User-Agent override, search page, then open the
first five jobs and read their descriptions. Every run is headless with the masking on.
This reaches LinkedIn: run it only when the user asks.
"""

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'offline-fingerprint-rung'))
from rung import CANDIDATE_ARGS, CHROME, HINTS, masked_user_agent, ua_override_params  # noqa: E402

PROFILE = str(Path('~/.lijs/chrome-profile').expanduser())
QUERY, GEO_ID, LOCATION = 'python', '103350119', 'Italy'
HOME = 'https://www.linkedin.com'
SEARCH = 'https://www.linkedin.com/jobs/search-results/?' + urlencode(
    {'keywords': QUERY, 'geoId': GEO_ID}
)
CARD_PREFIX = 'job-card-component-ref-'
SIGN_IN_PATHS = ('/uas/login', '/login', '/checkpoint/lg/login', '/authwall')
LIMIT = 5
SLOW_MO = 0.8

STATE = """(() => ({
  url: location.href,
  title: document.title,
  cards: Array.from(document.querySelectorAll('[componentkey^="job-card-component-ref-"]'))
    .map(e => e.getAttribute('componentkey').slice(23)),
  captcha: !!document.querySelector('iframe[src*="captcha"], iframe[src*="challenge"], #captcha-internal'),
  guest: !!document.querySelector('a[href*="/login"][data-tracking-control-name*="guest"], .nav__button-secondary'),
}))()"""


def flag(url: str) -> str | None:
    if '/checkpoint/challenge' in url or 'captcha' in url:
        return 'challenge'
    if any(p in url for p in SIGN_IN_PATHS):
        return 'sign-in'
    return None


def run_selenium(out: dict[str, Any]) -> None:
    import logging

    from linkedin_jobs_scraper import LinkedinScraper
    from linkedin_jobs_scraper.events import Events
    from linkedin_jobs_scraper.query import Location, Query, QueryOptions

    logging.basicConfig(level=logging.INFO)
    scraper = LinkedinScraper(chrome_user_data_dir=PROFILE, headless=True, max_workers=1, slow_mo=SLOW_MO)
    out['jobs'], out['errors'], out['events'] = [], [], []
    scraper.on(Events.DATA, lambda d: out['jobs'].append(
        {'id': d.job_id, 'title': d.title, 'location': d.location, 'description_len': len(d.description or '')}))
    scraper.on(Events.ERROR, lambda e: out['errors'].append(str(e)))
    scraper.on(Events.INVALID_SESSION, lambda: out['events'].append('invalid_session'))
    scraper.on(Events.END, lambda: out['events'].append('end'))
    scraper.run([Query(query=QUERY, options=QueryOptions(locations=[Location(geo_id=GEO_ID, name=LOCATION)], limit=LIMIT))])


async def run_candidate(stack: str, out: dict[str, Any], shots: Path) -> None:
    if stack == 'patchright':
        from patchright.async_api import async_playwright
    else:
        from pydoll.playwright.async_api import async_playwright

    ua = masked_user_agent()
    args = [*CANDIDATE_ARGS, f'--user-agent={ua}']
    kw: dict[str, Any] = {}
    pw = await async_playwright().start()
    if stack == 'patchright':
        # Keep third-party storage partitioning on: drop it from Patchright's default flag
        probe = await pw.chromium.launch_persistent_context(
            str(shots / 'probe-profile'), channel='chrome', headless=True)
        ps = subprocess.run(['ps', '-axww', '-o', 'args'], capture_output=True, text=True).stdout
        line = next(l for l in ps.splitlines() if 'probe-profile' in l and '--disable-features=' in l)
        default = next(a for a in line.split(' ') if a.startswith('--disable-features='))
        await probe.close()
        kept = ','.join(f for f in default.split('=', 1)[1].split(',') if f != 'ThirdPartyStoragePartitioning')
        args.append(f'--disable-features={kept}')
        kw = {'channel': 'chrome', 'ignore_default_args': [default]}
    else:
        kw = {'executable_path': CHROME}
    ctx = await pw.chromium.launch_persistent_context(PROFILE, headless=True, no_viewport=True, args=args, **kw)
    out['launch_cmdline'] = next(
        (l for l in subprocess.run(['ps', '-axww', '-o', 'args'], capture_output=True, text=True).stdout.splitlines()
         if PROFILE in l and '--type=' not in l), '')
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

    async def state(tag: str) -> dict[str, Any]:
        s = await ev(STATE)
        s['flag'] = flag(s['url'])
        try:
            s['li_at'] = any(c['name'] == 'li_at' for c in await ctx.cookies(HOME))
        except Exception as e:
            s['li_at'] = f'unreadable: {type(e).__name__}'
        s['t'] = round(time.time() - t0, 1)
        out['states'].append({'tag': tag, **{k: v for k, v in s.items() if k != 'cards'}, 'n_cards': len(s['cards'])})
        await page.screenshot(path=str(shots / f'{len(out["states"]):02d}-{tag}.png'))
        return s

    t0 = time.time()
    out['states'], out['jobs'] = [], []
    try:
        await page.goto(HOME, wait_until='commit', timeout=60000)
        await asyncio.sleep(SLOW_MO + 3)
        raw = await ev(HINTS)
        await cdp('Network.setUserAgentOverride', ua_override_params(raw, ua))
        out['ua_override'] = True
        s = await state('home')
        if s['flag'] or not s['li_at']:
            return
        await page.goto(SEARCH, wait_until='commit', timeout=60000)
        for _ in range(30):
            await asyncio.sleep(1)
            s = await ev(STATE)
            if s['cards'] or flag(s['url']) or s['captcha']:
                break
        s = await state('search')
        if s['flag'] or s['captcha']:
            return
        for job_id in list(dict.fromkeys(s['cards']))[:LIMIT]:
            await asyncio.sleep(SLOW_MO)
            await page.locator(f'[role="button"][componentkey="{CARD_PREFIX}{job_id}"]').click()
            about = page.locator(f'[componentkey="JobDetails_AboutTheJob_{job_id}"]')
            try:
                await about.wait_for(timeout=20000)
                text = ''
                for _ in range(20):
                    text = (await about.inner_text()).strip()
                    if text:
                        break
                    await asyncio.sleep(0.5)
            except Exception as e:
                text = ''
                out.setdefault('job_errors', []).append(f'{job_id}: {type(e).__name__}')
            out['jobs'].append({'id': job_id, 'description_len': len(text)})
        await state('after-jobs')
    finally:
        out['elapsed'] = round(time.time() - t0, 1)
        await ctx.close()
        await pw.stop()


def main() -> None:
    stack, out_dir = sys.argv[1], Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, Any] = {'stack': stack, 'started': time.strftime('%Y-%m-%d %H:%M:%S'),
                           'query': QUERY, 'location': LOCATION}
    try:
        if stack == 'selenium':
            run_selenium(out)
        else:
            asyncio.run(run_candidate(stack, out, out_dir))
    except Exception as e:
        out['error'] = f'{type(e).__name__}: {e}'
    (out_dir / 'result.json').write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in out.items() if k != 'launch_cmdline'}, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
