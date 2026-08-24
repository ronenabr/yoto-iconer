"""Scraper for the community icon library at yotoicons.com.

Unofficial: the site has no API, so this parses the `populate_icon_modal(...)`
call each result card carries. Responses are cached on disk and requests are
rate limited, because this is somebody's free, ad-free hobby site.
"""

from __future__ import annotations

import hashlib
import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config

BASE = "https://www.yotoicons.com"
USER_AGENT = "yoto-iconer/0.1 (+https://github.com/; personal MYO playlist tool)"
PER_PAGE = 25
_MIN_INTERVAL = 0.5  # seconds between live requests

_ICON_RE = re.compile(
    r"populate_icon_modal\(\s*'(\d+)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'\s*,"
    r"\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'(\d+)'\s*\)"
)
_COUNT_RE = re.compile(r"(\d[\d,]*)\s+(?:of our )?icons")

_last_request = 0.0


class ScrapeError(Exception):
    pass


def _throttle() -> None:
    global _last_request
    wait = _MIN_INTERVAL - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.time()


def _fetch(url: str, cache_ttl: int = 86400, binary: bool = False) -> bytes:
    cache = config.cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url.encode()).hexdigest()[:32]
    blob = cache / (key + (".bin" if binary else ".html"))
    if blob.exists() and (cache_ttl <= 0 or time.time() - blob.stat().st_mtime < cache_ttl):
        return blob.read_bytes()

    _throttle()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
    except urllib.error.HTTPError as exc:
        raise ScrapeError(f"{url} -> HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ScrapeError(f"{url} -> {exc.reason}") from exc
    blob.write_bytes(data)
    return data


def parse_page(markup: str) -> list[dict]:
    """Extract icon records from a yotoicons results page."""
    out = []
    for icon_id, category, tag1, tag2, artist, downloads in _ICON_RE.findall(markup):
        tags = [html.unescape(t).strip().lower() for t in (tag1, tag2) if t.strip()]
        out.append(
            {
                "id": icon_id,
                "category": html.unescape(category).strip().lower(),
                "title": html.unescape(tag1).strip() or html.unescape(category).strip(),
                "tags": tags,
                "artist": html.unescape(artist).strip(),
                "downloads": int(downloads),
            }
        )
    return out


def parse_total(markup: str) -> int | None:
    m = _COUNT_RE.search(html.unescape(markup))
    return int(m.group(1).replace(",", "")) if m else None


def page_url(page: int = 1, tag: str | None = None, sort: str = "popular") -> str:
    params = {"page": page, "sort": sort, "type": "singles"}
    if tag:
        params["tag"] = tag
    return f"{BASE}/icons?" + urllib.parse.urlencode(params)


def fetch_page(page: int = 1, tag: str | None = None, cache_ttl: int = 86400) -> list[dict]:
    markup = _fetch(page_url(page, tag), cache_ttl=cache_ttl).decode("utf-8", "replace")
    return parse_page(markup)


def search(tag: str, limit: int = 25, cache_ttl: int = 604800) -> list[dict]:
    """Live tag lookup, used when the local catalog has nothing good."""
    found: list[dict] = []
    page = 1
    while len(found) < limit and page <= 4:
        batch = fetch_page(page, tag=tag, cache_ttl=cache_ttl)
        if not batch:
            break
        found.extend(batch)
        if len(batch) < PER_PAGE:
            break
        page += 1
    return found[:limit]


def crawl(pages: int, progress=None) -> list[dict]:
    """Walk the popular-first listing, newest cache first."""
    seen: dict[str, dict] = {}
    for page in range(1, pages + 1):
        batch = fetch_page(page)
        if not batch:
            break
        for rec in batch:
            seen.setdefault(rec["id"], rec)
        if progress:
            progress(page, pages, len(seen))
        if len(batch) < PER_PAGE:
            break
    return list(seen.values())


def png_url(icon_id: str) -> str:
    return f"{BASE}/static/uploads/{icon_id}.png"


def download_png(icon_id: str) -> bytes:
    return _fetch(png_url(icon_id), cache_ttl=0, binary=True)
