"""Browser-backed, task-scoped acceptance checks for explicit page requirements."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.parse import unquote, urlsplit

from modai.core.contracts import AcceptanceContract
from tools.browser_gate import _QuietHandler


_DOM_PROBE = r"""() => {
  const visible = el => {
    if (!el) return false;
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) > 0
      && r.width > 0 && r.height > 0;
  };
  const text = el => (el?.innerText || '').trim();
  const validTarget = a => {
    const href = (a.getAttribute('href') || '').trim();
    if (!href || href === '#' || /^javascript:/i.test(href)) return false;
    if (href.startsWith('#')) {
      try { return visible(document.getElementById(decodeURIComponent(href.slice(1)))); }
      catch { return false; }
    }
    return /^https?:|^mailto:|^tel:/i.test(href) || !href.startsWith('#');
  };
  const main = document.querySelector('main, [role="main"]');
  const navs = [...document.querySelectorAll('nav, [role="navigation"]')].filter(visible);
  const navLinks = navs.flatMap(n => [...n.querySelectorAll('a[href]')]).filter(visible);
  const navInternal = navLinks.filter(a => (a.getAttribute('href') || '').startsWith('#') && validTarget(a));
  const heading = [...document.querySelectorAll('h1')].find(visible);
  const heroRegion = heading?.closest('section,header,main,[role="region"]');
  const hero = !!(heading && heroRegion && [...heroRegion.querySelectorAll('p')].some(p => visible(p) && text(p).length >= 12));
  const candidates = [...document.querySelectorAll('main section,main div,main ul,[role="main"] section,[role="main"] div')].slice(0, 500);
  let bestCards = [], bestLayout = false;
  for (const parent of candidates) {
    const kids = [...parent.children].filter(visible);
    const cards = kids.filter(el => {
      const h = el.querySelector('h2,h3,h4,h5,h6');
      return !el.querySelector('h1') && visible(h) && text(el).length >= 20;
    });
    if (cards.length < 2 || cards.length > 12 || cards.length < bestCards.length) continue;
    const ps = getComputedStyle(parent);
    const groupLayout = ['grid','flex'].includes(ps.display) && parseFloat(ps.gap || '0') >= 8;
    const styled = cards.every(el => {
      const s = getComputedStyle(el), outer = getComputedStyle(parent);
      const padding = Math.max(...['paddingTop','paddingRight','paddingBottom','paddingLeft'].map(k => parseFloat(s[k]) || 0));
      const border = Math.max(...['borderTopWidth','borderRightWidth','borderBottomWidth','borderLeftWidth'].map(k => parseFloat(s[k]) || 0));
      return padding >= 8 || border >= 1 || s.boxShadow !== 'none'
        || (s.backgroundColor !== 'rgba(0, 0, 0, 0)' && s.backgroundColor !== outer.backgroundColor);
    });
    if (cards.length > bestCards.length || (cards.length === bestCards.length && (groupLayout || styled))) {
      bestCards = cards; bestLayout = groupLayout || styled;
    }
  }
  const mainActions = [...(main || document.body).querySelectorAll('a[href],button')]
    .filter(el => visible(el) && text(el).length >= 2 && !navs.some(n => n.contains(el)));
  // An action in the hero or a dedicated section can be a CTA in any language.
  // Card links and navigation links do not substitute for a page-level CTA.
  const ctaActions = mainActions.filter(el => !bestCards.some(card => card.contains(el))
    && (heroRegion?.contains(el) || !!el.closest('section')));
  for (const el of ctaActions) el.setAttribute('data-modai-acceptance-cta', '');
  const usableCtas = ctaActions.filter(el => el.tagName === 'BUTTON'
    ? (el.disabled === false && el.tabIndex >= 0)
    : validTarget(el));
  const interactive = [...new Set([...navLinks, ...ctaActions])];
  const keyboard = interactive.every(el => el.tabIndex >= 0 && !el.disabled);
  const externalAssets = [...document.querySelectorAll('script[src],link[href],img[src],source[src],video[src],audio[src],iframe[src]')]
    .filter(el => el.tagName !== 'LINK' || /stylesheet|icon|preload/i.test(el.getAttribute('rel') || ''))
    .map(el => el.getAttribute('src') || el.getAttribute('href') || '')
    .filter(url => /^(?:https?:)?\/\//i.test(url));
  const styles = [...document.querySelectorAll('style')].map(el => el.textContent || '');
  if (styles.some(css => /@import\s|url\(\s*['"]?(?:https?:)?\/\//i.test(css))) externalAssets.push('remote CSS import/url');
  for (const el of document.querySelectorAll('[srcset]')) {
    if (/(?:https?:)?\/\//i.test(el.getAttribute('srcset') || '')) externalAssets.push('remote srcset');
  }
  const cardRects = bestCards.map(el => {
    const r = el.getBoundingClientRect(); return {x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width)};
  });
  return {
    main: visible(main), semantic: !!(visible(main) && document.querySelector('header,section,article,footer,nav')),
    nav: navs.length > 0, navLinks: navLinks.length, navTargetsValid: navLinks.length > 0 && navLinks.every(validTarget),
    navInternal: navInternal.length, hero, cardCount: bestCards.length, cardLayout: bestLayout, cardRects,
    ctaCount: ctaActions.length, usableCtas: usableCtas.length,
    ctaSection: usableCtas.some(el => !!el.closest('section')),
    keyboard, internalCss: styles.some(css => css.trim().length >= 12 && css.includes('{')),
    externalAssets: externalAssets.slice(0, 8),
    overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
    content: visible(main) && text(main).length >= 10,
  };
}"""


def evaluate_requirements(workspace: Path, contract: AcceptanceContract) -> dict[str, Any]:
    """Return explicit per-requirement evidence; never infer aesthetic approval."""
    index = workspace / "index.html"
    if not index.is_file():
        return {"verdict": "FAIL", "requirements": [], "errors": ["index.html not found"]}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"verdict": "FAIL", "requirements": [], "errors": ["Chromium/Playwright unavailable"]}
    observations: dict[str, dict[str, Any]] = {}
    handler = lambda *args, **kwargs: _QuietHandler(*args, directory=str(workspace), **kwargs)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    resolved_workspace = workspace.resolve()
    def local_route(route: Any) -> None:
        url = route.request.url
        if url.startswith(origin + "/"):
            relative = unquote(urlsplit(url).path).lstrip("/")
            target = (resolved_workspace / relative).resolve()
            if target == resolved_workspace or resolved_workspace in target.parents:
                route.continue_()
                return
        route.abort()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for name, width, height in (("mobile", 390, 844), ("desktop", 1440, 900)):
                    context = browser.new_context(viewport={"width": width, "height": height})
                    try:
                        page = context.new_page()
                        page.route("**/*", local_route)
                        page.goto(origin + "/index.html", wait_until="domcontentloaded", timeout=10000)
                        if name == "mobile" and page.locator('nav a:visible, [role="navigation"] a:visible').count() == 0:
                            toggle = page.locator('nav button:visible, [role="navigation"] button:visible').first
                            if toggle.count():
                                toggle.click(timeout=1500)
                        observation = page.evaluate(_DOM_PROBE)
                        reached_nav = reached_cta = False
                        for _ in range(32):
                            page.keyboard.press("Tab")
                            focused = page.evaluate("""() => {
                              const el = document.activeElement;
                              return {nav: !!el?.closest('nav,[role="navigation"]'),
                                cta: !!el?.hasAttribute('data-modai-acceptance-cta')};
                            }""")
                            reached_nav = reached_nav or focused["nav"]
                            reached_cta = reached_cta or focused["cta"]
                            if reached_nav and reached_cta:
                                break
                        observation["keyboardNav"] = reached_nav
                        observation["keyboardCta"] = reached_cta
                        observations[name] = observation
                    finally:
                        context.close()
            finally:
                browser.close()
    except Exception as exc:
        return {"verdict": "FAIL", "requirements": [], "errors": [f"acceptance browser unavailable: {type(exc).__name__}: {str(exc)[:160]}"]}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    mobile, desktop = observations["mobile"], observations["desktop"]
    results = []
    for item in contract.requirements:
        identifier = item.id
        ok, evidence = True, ""
        if identifier == "index_html":
            ok, evidence = index.stat().st_size > 0, "index.html exists and is nonempty"
        elif identifier == "semantic_html":
            ok, evidence = bool(desktop["semantic"]), "visible main and semantic section/header/article landmark required"
        elif identifier == "navigation":
            ok = all(view["nav"] and view["navTargetsValid"] and view["navInternal"] and view["keyboardNav"]
                     for view in (mobile, desktop))
            evidence = f"desktop nav={desktop['nav']}; links={desktop['navLinks']}; valid targets={desktop['navTargetsValid']}; internal targets={desktop['navInternal']}; keyboard Tab={desktop['keyboardNav']}; mobile keyboard Tab={mobile['keyboardNav']}"
        elif identifier == "hero":
            ok, evidence = bool(mobile["hero"] and desktop["hero"]), "visible h1 with supporting hero content on mobile and desktop"
        elif identifier == "feature_cards":
            expected = item.count
            ok = all((view["cardCount"] == expected if expected is not None else view["cardCount"] >= 2)
                     and view["cardLayout"] for view in (mobile, desktop))
            evidence = f"expected {expected if expected is not None else 'multiple'} styled/grouped cards; mobile={mobile['cardCount']} layout={mobile['cardLayout']}; desktop={desktop['cardCount']} layout={desktop['cardLayout']}"
        elif identifier == "cta":
            ok = bool(mobile["usableCtas"] and desktop["usableCtas"]
                      and mobile["keyboardCta"] and desktop["keyboardCta"])
            if "cta section" in item.statement.casefold():
                ok = ok and desktop["ctaSection"]
            evidence = f"reachable CTA actions: mobile={mobile['usableCtas']}, desktop={desktop['usableCtas']}; keyboard Tab={mobile['keyboardCta']}/{desktop['keyboardCta']}"
        elif identifier == "internal_css":
            ok, evidence = bool(desktop["internalCss"]), "nonempty embedded <style> rules required"
        elif identifier == "no_external_assets":
            ok, evidence = not desktop["externalAssets"], f"external asset references: {desktop['externalAssets']}"
        elif identifier == "responsive":
            ok = all(view["content"] and not view["overflow"] for view in (mobile, desktop))
            if any(req.id == "feature_cards" for req in contract.requirements):
                mrect, drect = mobile["cardRects"], desktop["cardRects"]
                ok = (ok and len(mrect) >= 2 and len(drect) >= 2
                      and abs(drect[0]["y"] - drect[1]["y"]) < 12
                      and abs(mrect[0]["y"] - mrect[1]["y"]) >= 12)
            evidence = f"mobile content={mobile['content']} overflow={mobile['overflow']}; desktop content={desktop['content']} overflow={desktop['overflow']}"
        results.append({"id": identifier, "source": item.source, "statement": item.statement,
                        "verdict": "PASS" if ok else "FAIL", "evidence": evidence})
    failed = [item for item in results if item["verdict"] == "FAIL"]
    return {"verdict": "FAIL" if failed else "PASS", "requirements": results,
            "errors": [f"{item['id']} ({item['source']}): {item['evidence']}" for item in failed]}
