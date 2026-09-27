"""Repeatable visual heuristics; not a subjective design or full WCAG verdict."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any


def contrast_ratio(foreground: str, background: str) -> float | None:
    def channels(value: str) -> list[float] | None:
        if not re.fullmatch(r'rgba?\([\d.,\s]+\)', value):
            return None
        numbers = [float(x) for x in re.findall(r'[\d.]+', value)]
        if len(numbers) not in (3, 4) or (len(numbers) == 4 and numbers[3] != 1):
            return None
        return [x / 255 for x in numbers[:3]] if all(0 <= x <= 255 for x in numbers[:3]) else None
    colors = [channels(foreground), channels(background)]
    if any(c is None for c in colors):
        return None
    luminances = []
    for color in colors:
        linear = [x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4 for x in color]
        luminances.append(sum(x * w for x, w in zip(linear, (.2126, .7152, .0722))))
    return (max(luminances) + .05) / (min(luminances) + .05)


def calibrate(workspace: Path, output: Path) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright
    from tools.browser_gate import VIEWPORTS
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for name, (width, height) in VIEWPORTS.items():
                page = browser.new_page(viewport={'width': width, 'height': height})
                # Calibration is local-only and must not fetch fonts or tracking.
                page.route('http://**/*', lambda route: route.abort())
                page.route('https://**/*', lambda route: route.abort())
                page.goto((workspace / 'index.html').resolve().as_uri(), wait_until='load')
                data = page.evaluate('''() => {
                  const shown=e=>{let r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&Number(s.opacity)>0};
                  const texts=[...document.querySelectorAll('h1,h2,p,a,button')].filter(shown).slice(0,250).map(e=>{
                    let s=getComputedStyle(e),bg='rgb(255, 255, 255)',image=false;
                    for(let n=e;n;n=n.parentElement){let t=getComputedStyle(n);if(t.backgroundImage!=='none')image=true;
                      if(t.backgroundColor!=='rgba(0, 0, 0, 0)'){bg=t.backgroundColor;break;}}
                    return {text:e.innerText.slice(0,100),color:s.color,background:bg,image,font:parseFloat(s.fontSize),weight:parseInt(s.fontWeight)};
                  });
                  const h=document.querySelector('h1'),b=document.querySelector('p');
                  const broken=[...document.querySelectorAll('a[href^="#"]')].filter(e=>e.hash.length>1&&!document.getElementById(decodeURIComponent(e.hash.slice(1)))).map(e=>e.hash);
                  return {texts,overflow:document.documentElement.scrollWidth>innerWidth+1,broken,
                    hierarchy:h&&b?parseFloat(getComputedStyle(h).fontSize)/parseFloat(getComputedStyle(b).fontSize):null};
                }''')
                failures = []
                unmeasured = 0
                for item in data['texts']:
                    ratio = None if item['image'] else contrast_ratio(item['color'], item['background'])
                    if ratio is None:
                        unmeasured += 1
                        continue
                    threshold = 3 if item['font'] >= 24 or (item['font'] >= 18.66 and item['weight'] >= 700) else 4.5
                    if ratio < threshold:
                        failures.append({'text': item['text'], 'contrast': round(ratio, 2), 'minimum': threshold})
                screenshot = output / f'{name}.png'
                page.screenshot(path=str(screenshot), full_page=True)
                issues = (['horizontal overflow'] if data['overflow'] else [])
                issues += [f'broken navigation {h}' for h in data['broken']]
                if data['hierarchy'] is not None and data['hierarchy'] < 1.5:
                    issues.append('weak headline/body size hierarchy (heuristic)')
                if failures:
                    issues.append('solid-background text contrast below threshold')
                reports.append({'viewport': name, 'issues': issues, 'contrast_failures': failures,
                                'unmeasured_texts': unmeasured, 'screenshot': str(screenshot)})
                page.close()
        finally:
            browser.close()
    return {'verdict': 'ISSUES' if any(r['issues'] for r in reports) else 'NO_HEURISTIC_ISSUES',
            'scope': 'local contrast/layout heuristics; not an aesthetic or complete accessibility PASS',
            'viewports': reports}
