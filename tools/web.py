from __future__ import annotations

import html
import ipaddress
import base64
import re
import socket
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from runtime_context import internet_enabled


def _validate_url(url: str) -> None:
    if not internet_enabled():
        raise PermissionError("İnternet araçları bu oturumda kapalı")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Yalnızca geçerli HTTP(S) adreslerine izin veriliyor")
    hostname = (parsed.hostname or "").lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        raise PermissionError("Yerel ağ adresleri web aracıyla açılamaz")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            addresses = {item[4][0] for item in socket.getaddrinfo(hostname, port)}
        except socket.gaierror as exc:
            raise ValueError(f"Adres çözümlenemedi: {hostname}") from exc
        if any(not ipaddress.ip_address(item).is_global for item in addresses):
            raise PermissionError("Özel/yerel ağa çözümlenen adresler web aracıyla açılamaz")
    else:
        if not address.is_global:
            raise PermissionError("Özel/yerel IP adresleri web aracıyla açılamaz")


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(url: str, max_bytes: int) -> str:
    _validate_url(url)
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 mod-agent/3.0"})
    with build_opener(_SafeRedirectHandler()).open(request, timeout=25) as response:
        raw = response.read(max_bytes)
    return raw.decode("utf-8", errors="replace")


def search_web(query: str, max_results: int = 6) -> str:
    if not query.strip():
        raise ValueError("Arama sorgusu boş olamaz")
    limit = max(1, min(int(max_results), 10))
    page = _download("https://www.bing.com/search?" + urlencode({"q": query}), 700_000)
    blocks = re.findall(r'<li class="b_algo".*?</li>', page, re.I | re.S)
    terms = {term for term in re.findall(r"[\w-]+", query.casefold()) if len(term) > 2}
    candidates: list[tuple[int, str, str, str]] = []
    for block in blocks:
        match = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.I | re.S)
        if not match:
            continue
        url, title = html.unescape(match.group(1)), match.group(2)
        parsed = urlparse(url)
        encoded = parse_qs(parsed.query).get("u", [""])[0]
        if "bing.com" in parsed.netloc and encoded.startswith("a1"):
            try:
                payload = encoded[2:]
                url = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                pass
        clean_title = re.sub(r"<[^>]+>", " ", title)
        clean_title = html.unescape(re.sub(r"\s+", " ", clean_title)).strip()
        snippet_match = re.search(r"<p[^>]*>(.*?)</p>", block, re.I | re.S)
        snippet = snippet_match.group(1) if snippet_match else ""
        clean_snippet = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", snippet))).strip()
        haystack = f"{clean_title} {url} {clean_snippet}".casefold()
        score = sum(1 for term in terms if term in haystack)
        candidates.append((score, clean_title, url, clean_snippet))
    candidates.sort(key=lambda item: item[0], reverse=True)
    results = [
        f"{index}. {title}\nURL: {url}\n{snippet}"
        for index, (_score, title, url, snippet) in enumerate(candidates[:limit], 1)
    ]
    return "\n\n".join(results) or "Arama sonucu bulunamadı."


def fetch_url(url: str, max_chars: int = 20000) -> str:
    max_chars = max(100, min(int(max_chars), 50000))
    text = _download(url, max_chars * 3)
    text = re.sub(r"(?is)<script.*?</script>", " ", text)
    text = re.sub(r"(?is)<style.*?</style>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()[:max_chars]
