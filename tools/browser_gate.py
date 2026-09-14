from __future__ import annotations

import json
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from runtime_context import get_workspace


VIEWPORTS = {
    "mobile": (390, 844),
    "landscape": (844, 390),
    "tablet": (768, 1024),
    "desktop": (1440, 900),
}


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *args: Any) -> None:
        return


def _probe_navigation_toggle(page: Any) -> list[str]:
    """Exercise an explicitly named menu toggle only when it hides nav links."""
    links = page.locator('nav a, [role="navigation"] a')
    hidden = [link for link in links.all()[:40] if not link.is_visible()]
    if not hidden:
        return []
    for button in page.locator('nav button, [role="navigation"] button').all()[:8]:
        label = (button.get_attribute('aria-label') or '') + ' ' + button.inner_text() + ' ' + (button.get_attribute('class') or '')
        if not button.is_visible() or not re.search(r'menu|menü|navigation', label, re.I):
            continue
        try:
            button.click(timeout=1500)
            # Wait for real visibility, accommodating CSS/JS transitions.
            from playwright.sync_api import expect
            expect(hidden[0]).to_be_visible(timeout=1500)
            return []
        except Exception:
            return ['navigation menu toggle does not reveal hidden links']
    return []


def validate_browser_quality(path: str = ".") -> str:
    """Render a local static site and enforce visual/runtime quality gates."""
    workspace = get_workspace().resolve()
    root = (workspace / path).resolve()
    if root != workspace and workspace not in root.parents:
        raise ValueError("Path escapes workspace")
    site_root = root if root.is_dir() else root.parent
    index = site_root / "index.html" if root.is_dir() else root
    if not index.is_file():
        return json.dumps({"verdict": "FAIL", "errors": ["index.html not found"], "viewports": []})
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError:
        return json.dumps({
            "verdict": "FAIL",
            "errors": ["Playwright is not installed; run ./setup.sh or python -m playwright install chromium"],
            "viewports": [],
        })

    output = site_root / ".modai" / "browser"
    output.mkdir(parents=True, exist_ok=True)
    handler = lambda *args, **kwargs: _QuietHandler(*args, directory=str(site_root), **kwargs)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/{index.relative_to(site_root).as_posix()}"
    reports: list[dict[str, Any]] = []
    top_errors: list[str] = []
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Error as exc:
                return json.dumps({
                    "verdict": "FAIL", "errors": [f"Chromium unavailable: {exc}"], "viewports": [],
                })
            try:
                for name, (width, height) in VIEWPORTS.items():
                    context = browser.new_context(viewport={"width": width, "height": height})
                    page = context.new_page()
                    console_errors: list[str] = []
                    runtime_errors: list[str] = []
                    page.on("console", lambda msg, bucket=console_errors: bucket.append(msg.text) if msg.type == "error" else None)
                    page.on("pageerror", lambda exc, bucket=runtime_errors: bucket.append(str(exc)))
                    response = page.goto(url, wait_until="networkidle", timeout=15000)
                    metrics = page.evaluate("""() => {
                      const visible = el => { const s=getComputedStyle(el), r=el.getBoundingClientRect();
                        return s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) > 0 && r.width > 0 && r.height > 0; };
                      const anchors = [...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'));
                      const brokenAnchors = anchors.filter(h => h && h.startsWith('#') && h !== '#'
                        && !document.getElementById(decodeURIComponent(h.slice(1))));
                      return {
                        scrollWidth: document.documentElement.scrollWidth,
                        innerWidth: window.innerWidth,
                        textLength: (document.body?.innerText || '').trim().length,
                        visibleElements: [...document.body.querySelectorAll('h1,h2,p,a,button,img,main,section')].filter(visible).length,
                        brokenAnchors,
                        localLinks: anchors.filter(h => h && !h.startsWith('#') && !/^(?:https?:|mailto:|tel:|javascript:)/i.test(h))
                      };
                    }""")
                    errors: list[str] = []
                    if response is None or response.status >= 400:
                        errors.append(f"navigation status {getattr(response, 'status', 'none')}")
                    if metrics["scrollWidth"] > metrics["innerWidth"] + 1:
                        errors.append(f"horizontal overflow {metrics['scrollWidth']}>{metrics['innerWidth']}")
                    if metrics["textLength"] == 0 or metrics["visibleElements"] == 0:
                        errors.append("page has no visible content")
                    if metrics["brokenAnchors"]:
                        errors.append("broken anchors: " + ", ".join(metrics["brokenAnchors"][:8]))
                    if name == "desktop":
                        for href in dict.fromkeys(metrics["localLinks"]):
                            link_response = context.request.get(urljoin(url, href), timeout=5000)
                            if not link_response.ok:
                                errors.append(f"broken local navigation: {href} ({link_response.status})")
                    screenshot = output / f"{name}.png"
                    page.screenshot(path=str(screenshot), full_page=True)
                    errors.extend(_probe_navigation_toggle(page))
                    errors.extend(f"console: {item}" for item in console_errors)
                    errors.extend(f"javascript: {item}" for item in runtime_errors)
                    reports.append({
                        "name": name, "width": width, "height": height,
                        "status": "PASS" if not errors else "FAIL", "errors": errors,
                        "screenshot": str(screenshot.relative_to(site_root)),
                    })
                    context.close()
            finally:
                browser.close()
    except Exception as exc:
        top_errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    failed = top_errors or any(item["status"] == "FAIL" for item in reports)
    return json.dumps({
        "verdict": "FAIL" if failed else "PASS", "errors": top_errors,
        "viewports": reports, "artifact_directory": str(output.relative_to(site_root)),
    }, ensure_ascii=False)
