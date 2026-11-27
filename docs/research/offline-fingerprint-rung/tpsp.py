# ruff: noqa
"""Patchright with third-party storage partitioning left on: does rebrowser still flag it?"""
import asyncio, subprocess, tempfile
from patchright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        prof = tempfile.mkdtemp(prefix='rung-tpsp-')
        ctx = await p.chromium.launch_persistent_context(prof, channel='chrome', headless=True, no_viewport=True)
        ps = subprocess.run(['ps', '-axww', '-o', 'args'], capture_output=True, text=True).stdout
        line = next(l for l in ps.splitlines() if prof in l and '--disable-features=' in l)
        flag = next(a for a in line.split(' ') if a.startswith('--disable-features='))
        await ctx.close()
        kept = ','.join(f for f in flag.split('=', 1)[1].split(',') if f != 'ThirdPartyStoragePartitioning')
        ctx = await p.chromium.launch_persistent_context(
            tempfile.mkdtemp(prefix='rung-tpsp-'), channel='chrome', headless=False, no_viewport=True,
            ignore_default_args=[flag], args=[f'--disable-features={kept}'])
        page = ctx.pages[0]
        await page.goto('https://bot-detector.rebrowser.net/')
        await asyncio.sleep(8)
        t = await page.evaluate('document.body.innerText')
        print('\n'.join(l for l in t.splitlines() if l.startswith(('🔴', '🟡'))) or 'no red/yellow')
        await page.goto('https://httpbin.org/get'); await asyncio.sleep(1)
        await ctx.close()

asyncio.run(main())
