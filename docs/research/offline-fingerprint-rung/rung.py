# ruff: noqa  throwaway research harness, outside the package
"""
Offline fingerprint rung: one stack, one mode, every public bot-detection page.

Usage: python rung.py <stack> <mode> <out_dir>
  stack: selenium | patchright | sb-uc | sb-cdp | pydoll | zendriver
  mode:  headed | headless-raw | headless-masked

Throwaway research code. Nothing here reaches LinkedIn.
"""

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# Path to the installed Google Chrome executable
CHROME = __import__('os').environ['CHROME_PATH']
WIDTH, HEIGHT = 1472, 828

# Flags the candidates get on top of their own defaults: what the package needs from any stack
CANDIDATE_ARGS = [
    '--use-mock-keychain',
    '--password-store=basic',
    '--lang=en-GB',
    f'--window-size={WIDTH},{HEIGHT}',
]

PROBE = """JSON.stringify((() => {
  let gl = {};
  try {
    const c = document.createElement('canvas').getContext('webgl');
    const e = c.getExtension('WEBGL_debug_renderer_info');
    gl = {vendor: c.getParameter(e.UNMASKED_VENDOR_WEBGL), renderer: c.getParameter(e.UNMASKED_RENDERER_WEBGL)};
  } catch (x) { gl = {error: String(x)}; }
  return {
    webdriver: navigator.webdriver,
    userAgent: navigator.userAgent,
    brands: navigator.userAgentData && navigator.userAgentData.brands.map(b => b.brand + ' ' + b.version),
    platform: navigator.platform,
    languages: navigator.languages,
    plugins: navigator.plugins.length,
    mimeTypes: navigator.mimeTypes.length,
    hardwareConcurrency: navigator.hardwareConcurrency,
    deviceMemory: navigator.deviceMemory,
    chromeRuntime: typeof window.chrome, chromeKeys: window.chrome ? Object.keys(window.chrome) : null,
    notification: typeof Notification !== 'undefined' ? Notification.permission : null,
    outer: [window.outerWidth, window.outerHeight], inner: [window.innerWidth, window.innerHeight],
    screen: [screen.width, screen.height, screen.availWidth, screen.availHeight, screen.colorDepth],
    devicePixelRatio: window.devicePixelRatio,
    webgl: gl,
    cdcKeys: Object.keys(window).filter(k => /^cdc_|^\\$cdc|__playwright|__pw|__nightmare|_selenium|domAutomation/.test(k)),
  };
})())"""

HINTS = """navigator.userAgentData ? navigator.userAgentData.getHighEntropyValues(
  ['architecture', 'bitness', 'model', 'platformVersion', 'fullVersionList']
).then(v => JSON.stringify({brands: navigator.userAgentData.brands, hints: v})) : null"""

# url, seconds to settle, whether to call the rebrowser main-world probe
PAGES = [
    ('headers', 'https://httpbin.org/headers', 3),
    ('sannysoft', 'https://bot.sannysoft.com/', 8),
    ('rebrowser', 'https://bot-detector.rebrowser.net/', 6),
    ('deviceandbrowserinfo', 'https://deviceandbrowserinfo.com/are_you_a_bot', 10),
    ('botd', 'https://fingerprintjs.github.io/BotD/main/', 8),
    ('creepjs', 'https://abrahamjuliot.github.io/creepjs/', 25),
    ('browserscan', 'https://www.browserscan.net/bot-detection', 15),
]

if __import__('os').environ.get('SMOKE'):
    PAGES = [p for p in PAGES if p[0] in ('headers', 'rebrowser')]

TEXT = 'document.body ? document.body.innerText : ""'


def masked_user_agent() -> str:
    from linkedin_jobs_scraper.utils.chrome_driver import resolve_masked_user_agent

    ua = resolve_masked_user_agent()
    assert ua, 'no masked user agent'
    return ua


def ua_override_params(raw: str, masked: str) -> dict[str, Any]:
    """Same values mask_headless_user_agent sends"""
    data = json.loads(raw)
    hints = data['hints']
    return {
        'userAgent': masked,
        'userAgentMetadata': {
            'brands': data['brands'],
            'fullVersionList': hints.get('fullVersionList', data['brands']),
            'platform': hints.get('platform', ''),
            'platformVersion': hints.get('platformVersion', ''),
            'architecture': hints.get('architecture', ''),
            'model': hints.get('model', ''),
            'bitness': hints.get('bitness', ''),
            'mobile': bool(hints.get('mobile', False)),
            'wow64': bool(hints.get('wow64', False)),
        },
    }


class Session:
    """Each stack adapts to: open, goto, eval (main world, returns a value), shot, cdp, close"""

    masked: str | None = None
    isolated_eval: bool = False

    async def open(self, mode: str, profile: str, ua: str | None) -> None: ...
    async def goto(self, url: str) -> None: ...
    async def eval(self, expr: str, isolated: bool = False) -> Any: ...
    async def shot(self, path: Path) -> None: ...
    async def cdp(self, method: str, params: dict[str, Any]) -> None: ...
    async def close(self) -> None: ...


class SeleniumSession(Session):
    """The package's own launch: build_driver and mask_headless_user_agent"""

    async def open(self, mode: str, profile: str, ua: str | None) -> None:
        from linkedin_jobs_scraper.utils.chrome_driver import (
            build_driver,
            get_default_driver_options,
        )

        def launch() -> Any:
            if mode == 'headless-raw':
                opts = get_default_driver_options(headless=True, chrome_user_data_dir=profile)
                return build_driver(options=opts)
            return build_driver(headless=mode != 'headed', chrome_user_data_dir=profile)

        self.d = await asyncio.to_thread(launch)

    async def goto(self, url: str) -> None:
        await asyncio.to_thread(self.d.get, url)

    async def eval(self, expr: str, isolated: bool = False) -> Any:
        if expr == HINTS:
            return await asyncio.to_thread(
                self.d.execute_async_script,
                f'const cb = arguments[arguments.length-1]; Promise.resolve({expr}).then(cb, () => cb(null));',
            )
        return await asyncio.to_thread(self.d.execute_script, f'return {expr}')

    async def shot(self, path: Path) -> None:
        await asyncio.to_thread(self.d.save_screenshot, str(path))

    async def cdp(self, method: str, params: dict[str, Any]) -> None:
        await asyncio.to_thread(self.d.execute_cdp_cmd, method, params)

    async def close(self) -> None:
        await asyncio.to_thread(self.d.quit)


class SbUcSession(SeleniumSession):
    """SeleniumBase UC mode: a patched chromedriver, still the Selenium API"""

    async def open(self, mode: str, profile: str, ua: str | None) -> None:
        from seleniumbase import Driver

        def launch() -> Any:
            kw: dict[str, Any] = dict(
                uc=True,
                headless=mode != 'headed',
                user_data_dir=profile,
                binary_location=CHROME,
                locale_code='en-GB',
            )
            if ua:
                kw['agent'] = ua
            return Driver(**kw)

        self.d = await asyncio.to_thread(launch)

    async def goto(self, url: str) -> None:
        # UC mode's own advice: drop the driver connection while the page loads
        await asyncio.to_thread(self.d.uc_open_with_reconnect, url, 3)


class PatchrightSession(Session):
    async def open(self, mode: str, profile: str, ua: str | None) -> None:
        from patchright.async_api import async_playwright

        self.pw = await async_playwright().start()
        args = list(CANDIDATE_ARGS)
        if ua:
            args.append(f'--user-agent={ua}')
        self.ctx = await self.pw.chromium.launch_persistent_context(
            user_data_dir=profile,
            channel='chrome',
            headless=mode != 'headed',
            no_viewport=True,
            args=args,
        )
        self.page = self.ctx.pages[0] if self.ctx.pages else await self.ctx.new_page()

    async def goto(self, url: str) -> None:
        await self.page.goto(url, wait_until='domcontentloaded', timeout=60000)

    async def eval(self, expr: str, isolated: bool = False) -> Any:
        return await self.page.evaluate(expr, isolated_context=isolated)

    async def shot(self, path: Path) -> None:
        await self.page.screenshot(path=str(path))

    async def cdp(self, method: str, params: dict[str, Any]) -> None:
        s = await self.ctx.new_cdp_session(self.page)
        await s.send(method, params)

    async def close(self) -> None:
        await self.ctx.close()
        await self.pw.stop()


class ZendriverSession(Session):
    async def open(self, mode: str, profile: str, ua: str | None) -> None:
        import zendriver as zd

        args = [a for a in CANDIDATE_ARGS if not a.startswith('--lang')]
        if ua:
            args.append(f'--user-agent={ua}')
        self.b = await zd.start(
            headless=mode != 'headed',
            user_data_dir=profile,
            browser_executable_path=CHROME,
            browser_args=args,
            lang='en-GB',
        )
        self.tab = self.b.main_tab

    async def goto(self, url: str) -> None:
        self.tab = await self.b.get(url)

    async def eval(self, expr: str, isolated: bool = False) -> Any:
        return await self.tab.evaluate(expr, await_promise=True)

    async def shot(self, path: Path) -> None:
        await self.tab.save_screenshot(str(path))

    async def cdp(self, method: str, params: dict[str, Any]) -> None:
        from zendriver import cdp

        meta = cdp.emulation.UserAgentMetadata.from_json(params['userAgentMetadata'])
        await self.tab.send(
            cdp.network.set_user_agent_override(
                user_agent=params['userAgent'], user_agent_metadata=meta
            )
        )

    async def close(self) -> None:
        await self.b.stop()


class SbCdpSession(Session):
    """SeleniumBase pure CDP mode (sb_cdp.Chrome), no chromedriver"""

    async def open(self, mode: str, profile: str, ua: str | None) -> None:
        from seleniumbase import sb_cdp

        args = [a for a in CANDIDATE_ARGS if not a.startswith('--lang')]
        kw: dict[str, Any] = dict(
            headless=mode != 'headed',
            user_data_dir=profile,
            browser_executable_path=CHROME,
            browser_args=args,
            lang='en-GB',
        )
        if ua:
            kw['agent'] = ua
        # sb_cdp drives its own event loop, so it lives on a worker thread
        self.sb = await asyncio.to_thread(lambda: sb_cdp.Chrome(**kw))

    async def goto(self, url: str) -> None:
        await asyncio.to_thread(self.sb.open, url)

    async def eval(self, expr: str, isolated: bool = False) -> Any:
        return await asyncio.to_thread(
            lambda: self.sb.loop.run_until_complete(self.sb.page.evaluate(expr, await_promise=True))
        )

    async def shot(self, path: Path) -> None:
        await asyncio.to_thread(self.sb.save_screenshot, path.name, str(path.parent))

    async def cdp(self, method: str, params: dict[str, Any]) -> None:
        import mycdp

        meta = mycdp.emulation.UserAgentMetadata.from_json(params['userAgentMetadata'])
        cmd = mycdp.network.set_user_agent_override(
            user_agent=params['userAgent'], user_agent_metadata=meta
        )
        await asyncio.to_thread(lambda: self.sb.loop.run_until_complete(self.sb.page.send(cmd)))

    async def close(self) -> None:
        await asyncio.to_thread(self.sb.driver.stop)


class PydollSession(Session):
    async def open(self, mode: str, profile: str, ua: str | None) -> None:
        from pydoll.browser import Chrome
        from pydoll.browser.options import ChromiumOptions

        o = ChromiumOptions()
        o.binary_location = CHROME
        for a in CANDIDATE_ARGS:
            o.add_argument(a)
        o.add_argument(f'--user-data-dir={profile}')
        if ua:
            o.add_argument(f'--user-agent={ua}')
        o.headless = mode != 'headed'
        self.b = Chrome(options=o)
        self.tab = await self.b.start()

    async def goto(self, url: str) -> None:
        await self.tab.go_to(url, timeout=60)

    async def eval(self, expr: str, isolated: bool = False) -> Any:
        r = await self.tab.execute_script(expr, await_promise=True, return_by_value=True)
        return r['result']['result'].get('value')

    async def shot(self, path: Path) -> None:
        await self.tab.take_screenshot(str(path))

    async def cdp(self, method: str, params: dict[str, Any]) -> None:
        await self.tab._execute_command({'method': method, 'params': params})

    async def close(self) -> None:
        await self.b.stop()


class PydollPlaywrightSession(PatchrightSession):
    """Pydoll's Playwright-compatible layer: Playwright code, Pydoll underneath"""

    async def open(self, mode: str, profile: str, ua: str | None) -> None:
        from pydoll.playwright.async_api import async_playwright

        self.pw = await async_playwright().start()
        args = list(CANDIDATE_ARGS)
        if ua:
            args.append(f'--user-agent={ua}')
        self.ctx = await self.pw.chromium.launch_persistent_context(
            profile, executable_path=CHROME, headless=mode != 'headed', no_viewport=True, args=args
        )
        self.page = self.ctx.pages[0] if self.ctx.pages else await self.ctx.new_page()

    async def eval(self, expr: str, isolated: bool = False) -> Any:
        return await self.page.evaluate(expr)

    async def cdp(self, method: str, params: dict[str, Any]) -> None:
        # The layer has no new_cdp_session; raw CDP goes through the underlying Pydoll tab
        await self.page.tab.execute_command({'method': method, 'params': params})


STACKS: dict[str, type[Session]] = {
    'selenium': SeleniumSession,
    'patchright': PatchrightSession,
    'sb-uc': SbUcSession,
    'sb-cdp': SbCdpSession,
    'pydoll': PydollSession,
    'zendriver': ZendriverSession,
    'pydoll-pw': PydollPlaywrightSession,
}


async def run(stack: str, mode: str, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    ua = masked_user_agent() if mode == 'headless-masked' else None
    s = STACKS[stack]()
    result: dict[str, Any] = {'stack': stack, 'mode': mode, 'launch_ua': ua, 'pages': {}}
    profile = tempfile.mkdtemp(prefix=f'rung-{stack}-')
    t0 = time.time()
    try:
        # Selenium resolves and passes the masked User-Agent itself, inside build_driver
        await asyncio.wait_for(s.open(mode, profile, None if stack == 'selenium' else ua), 120)
        result['launch_seconds'] = round(time.time() - t0, 1)
        masked_done = False
        for name, url, settle in PAGES:
            page: dict[str, Any] = {}
            try:
                await asyncio.wait_for(s.goto(url), 90)
                if mode == 'headless-masked' and not masked_done:
                    # The package masks over CDP on the first secure page, before anything else
                    if stack in ('selenium', 'sb-uc'):
                        from linkedin_jobs_scraper.utils.chrome_driver import (
                            mask_headless_user_agent,
                        )

                        result['cdp_masked'] = await asyncio.to_thread(
                            mask_headless_user_agent, s.d
                        )  # type: ignore[attr-defined]
                    else:
                        raw = await s.eval(HINTS)
                        await s.cdp(
                            'Network.setUserAgentOverride', ua_override_params(raw, ua or '')
                        )
                        result['cdp_masked'] = ua
                    masked_done = True
                    await asyncio.wait_for(s.goto(url), 90)
                await asyncio.sleep(settle)
                if name == 'rebrowser':
                    # The page's own triggers: DOM calls it watches for, then its main-world function
                    triggers = (
                        "(document.getElementById('detections-json'),"
                        " document.getElementsByClassName('div'), 1)"
                    )
                    if stack == 'pydoll-pw':
                        page['locator_count'] = await s.page.locator('td').count()
                        await asyncio.sleep(3)
                        page['text_locator_only'] = await s.eval(TEXT)
                    if stack == 'patchright':
                        await s.eval(triggers, isolated=True)
                        await asyncio.sleep(3)
                        page['text_isolated_only'] = await s.eval(TEXT, isolated=True)
                    await s.eval(triggers)
                    await s.eval('typeof window.dummyFn === "function" ? (window.dummyFn(), 1) : 0')
                    await asyncio.sleep(3)
                if name == 'sannysoft':
                    page['probe'] = json.loads(await s.eval(PROBE, isolated=stack == 'patchright'))
                page['text'] = await s.eval(TEXT, isolated=stack == 'patchright')
                await s.shot(out / f'{name}.png')
            except Exception as e:  # noqa: BLE001 throwaway harness: record and move on
                page['error'] = f'{type(e).__name__}: {e}'[:500]
            result['pages'][name] = page
    except Exception as e:  # noqa: BLE001
        result['error'] = f'{type(e).__name__}: {e}'[:1000]
    finally:
        try:
            await asyncio.wait_for(s.close(), 30)
        except Exception as e:  # noqa: BLE001
            result['close_error'] = f'{type(e).__name__}: {e}'[:300]
    (out / 'result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(run(sys.argv[1], sys.argv[2], Path(sys.argv[3])))
