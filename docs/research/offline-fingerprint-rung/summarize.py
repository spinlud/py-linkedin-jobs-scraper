# ruff: noqa
"""Reduce results/<stack>/<mode>/result.json to the signals each page reports. Throwaway."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent / 'results'
STACKS = ['selenium', 'patchright', 'sb-uc', 'sb-cdp', 'pydoll', 'zendriver', 'pydoll-pw']
MODES = ['headless-raw', 'headless-masked', 'headed']


def rebrowser(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        if line.startswith(('🔴', '🟡')):
            name = line.split('\t')[0]
            out.append(
                name.replace('🔴', 'R:').replace('🟡', 'Y:').replace('️', '').replace(' ', '')
            )
    return out


def json_block(text: str, key: str) -> dict | None:
    i = text.find('{')
    while i != -1:
        depth = 0
        for j in range(i, len(text)):
            depth += {'{': 1, '}': -1}.get(text[j], 0)
            if depth == 0:
                try:
                    d = json.loads(text[i : j + 1])
                    if key in d:
                        return d
                except json.JSONDecodeError:
                    pass
                break
        i = text.find('{', i + 1)
    return None


def dabi(text: str) -> list[str]:
    d = json_block(text, 'isBot')
    if not d:
        return ['?']
    return (['BOT'] if d['isBot'] else ['human']) + [
        k for k, v in d['details'].items() if v is True
    ]


def botd(text: str) -> str:
    d = json_block(text, 'bot')
    if not d:
        return '?'
    return f'bot:{d.get("botKind")}' if d['bot'] else 'human'


def creep(text: str) -> str:
    vals = dict((k, v) for v, k in re.findall(r'(\d+)% (like headless|headless|stealth)', text))
    return '/'.join(vals.get(k, '?') for k in ('like headless', 'headless', 'stealth'))


def browserscan(text: str) -> list[str]:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out = []
    for a, b in zip(lines, lines[1:]):
        if b in ('Robot', 'Abnormal') and a not in ('Test Results:',):
            out.append(f'{a}={b}')
    verdict = '?'
    if 'Test Results:' in lines:
        verdict = lines[lines.index('Test Results:') + 1]
    return [verdict] + out


def sanny(text: str) -> list[str]:
    lines = text.splitlines()
    failed = []
    for i, l in enumerate(lines):
        if 'failed' in l and 'passed' not in l:
            name = l.split('\t')[0].strip() or (lines[i - 2] if i >= 2 else '?')
            failed.append(name.strip())
    return failed


def headers(text: str) -> list[str]:
    d = json_block(text, 'headers')
    if not d:
        return ['?']
    h = d['headers']
    out = []
    if 'HeadlessChrome' in h.get('User-Agent', ''):
        out.append('UA:HeadlessChrome')
    ch = h.get('Sec-Ch-Ua')
    if ch is None or ch == '':
        out.append('Sec-Ch-Ua:empty')
    elif 'Headless' in ch:
        out.append('Sec-Ch-Ua:Headless')
    return out or ['ok']


def probe(p: dict | None) -> list[str]:
    if not p:
        return ['?']
    out = []
    if p.get('webdriver'):
        out.append('webdriver')
    if p.get('cdcKeys'):
        out.append('cdc_vars')
    if 'Headless' in (p.get('userAgent') or ''):
        out.append('navigator.UA:Headless')
    if any('Headless' in b for b in p.get('brands') or []):
        out.append('brands:Headless')
    if p.get('screen', [0, 0])[:2] == [800, 600]:
        out.append('screen800x600')
    gl = p.get('webgl') or {}
    if 'error' in gl:
        out.append('no-webgl')
    elif 'SwiftShader' in str(gl.get('renderer')):
        out.append('webgl:SwiftShader')
    if p.get('plugins') == 0:
        out.append('plugins0')
    return out or ['ok']


def row(stack: str, mode: str) -> dict:
    f = ROOT / stack / mode / 'result.json'
    if not f.exists():
        return {'stack': stack, 'mode': mode, 'missing': True}
    r = json.loads(f.read_text())
    p = r['pages']
    t = lambda n: p.get(n, {}).get('text') or ''
    errs = {n: v['error'] for n, v in p.items() if 'error' in v}
    out = {
        'stack': stack,
        'mode': mode,
        'error': r.get('error'),
        'page_errors': errs,
        'headers': headers(t('headers')),
        'probe': probe(p.get('sannysoft', {}).get('probe')),
        'sannysoft_failed': sanny(t('sannysoft')),
        'rebrowser': rebrowser(t('rebrowser')),
        'deviceandbrowserinfo': dabi(t('deviceandbrowserinfo')),
        'botd': botd(t('botd')),
        'creepjs_likeheadless/headless/stealth': creep(t('creepjs')),
        'browserscan': browserscan(t('browserscan')),
    }
    if 'text_isolated_only' in p.get('rebrowser', {}):
        out['rebrowser_isolated_only'] = rebrowser(p['rebrowser']['text_isolated_only'])
    return out


if __name__ == '__main__':
    rows = [row(s, m) for s in STACKS for m in MODES]
    json.dump(rows, sys.stdout, indent=1, ensure_ascii=False)
