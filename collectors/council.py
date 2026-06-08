"""Council news, meetings and decisions affecting Oxted & Hurst Green.

Scrapes three pages directly (the old RSS feed at /rss/news was dead and a
header-less client is served an empty page, so this collector returned 0
items):

  1. Tandridge District Council — News
     https://www.tandridge.gov.uk/Your-council/News
  2. Tandridge District Council — Meetings & decisions
     https://www.tandridge.gov.uk/Your-council/Meetings-and-decisions/Meetings
  3. Oxted Parish Council — Meetings
     http://oxted-pc.org.uk/meetings/

Tandridge DC is the local authority for Oxted & Hurst Green, so its news and
meeting agendas are relevant to residents; Oxted PC items are tagged
``local: true``. Each source:

  * sends realistic browser headers and follows redirects (matching
    ``planning.py``, which works around Tandridge blocking header-less clients);
  * parses content-area anchors with a generic, resilient link parser that
    filters out nav/cookie/privacy chrome;
  * resolves every href to an absolute working URL (``urljoin``);
  * extracts a best-effort date from the link text or surrounding markup.

Per-source error isolation means one failing site can't sink the others.
Results are de-duplicated by URL, sorted newest-first and capped at 30.
"""
import hashlib
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .base import BaseCollector, CollectionResult, Item, now_iso

TANDRIDGE_BASE = "https://www.tandridge.gov.uk"
NEWS_URL = "https://www.tandridge.gov.uk/Your-council/News"
MEETINGS_URL = (
    "https://www.tandridge.gov.uk/Your-council/Meetings-and-decisions/Meetings"
)
OXTED_PC_BASE = "http://oxted-pc.org.uk"
OXTED_PC_URL = "http://oxted-pc.org.uk/meetings/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.5",
}

# Anchor text / hrefs that are site chrome rather than real content links.
_SKIP_RE = re.compile(
    r"\b(cookie|privacy|accessibility|sitemap|contact us|sign in|log in|"
    r"skip to|search|home|terms|disclaimer|feedback|complaints|newsletter|"
    r"facebook|twitter|instagram|youtube|linkedin)\b",
    re.IGNORECASE,
)

# Date shapes found in link text / nearby markup:
#   "1 June 2026", "01 Jun 2026", "2026-06-01", "01/06/2026"
_DATE_TEXT_RE = re.compile(
    r"\b(\d{1,2})\s+"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+"
    r"(\d{4})\b",
    re.IGNORECASE,
)
_DATE_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DATE_SLASH_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _extract_date(*texts: str) -> str:
    """Best-effort YYYY-MM-DD from any of the given strings; today on failure."""
    for text in texts:
        if not text:
            continue
        m = _DATE_ISO_RE.search(text)
        if m:
            return m.group(0)
        m = _DATE_TEXT_RE.search(text)
        if m:
            month = _MONTHS[m.group(2).lower()[:3]]
            return f"{int(m.group(3)):04d}-{month:02d}-{int(m.group(1)):02d}"
        m = _DATE_SLASH_RE.search(text)
        if m:
            return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return now_iso()[:10]


class CouncilCollector(BaseCollector):
    name = "council"

    def collect(self) -> CollectionResult:
        seen: set[str] = set()
        items: list[Item] = []

        for label, fetch in (
            ("Tandridge news", lambda: self._scrape(
                NEWS_URL, TANDRIDGE_BASE, seen,
                category="council-news", local=False, source="tandridge_news")),
            ("Tandridge meetings", lambda: self._scrape(
                MEETINGS_URL, TANDRIDGE_BASE, seen,
                category="council-meeting", local=False, source="tandridge_meetings")),
            ("Oxted PC meetings", lambda: self._scrape(
                OXTED_PC_URL, OXTED_PC_BASE, seen,
                category="council-meeting", local=True, source="oxted_pc")),
        ):
            try:
                items.extend(fetch())
            except Exception as exc:  # per-source isolation
                print(f"[council] {label} failed: {exc}")

        items.sort(key=lambda x: x.date, reverse=True)
        return CollectionResult(source=self.name, collected_at=now_iso(), items=items[:30])

    # ── generic content-link scraper ──────────────────────────────────────
    def _scrape(self, url: str, base: str, seen: set[str], *,
                category: str, local: bool, source: str) -> list[Item]:
        resp = httpx.get(url, headers=_HEADERS, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Scope to the main content region when the page marks one, so we skip
        # the header/nav/footer chrome; fall back to the whole document.
        root = (
            soup.find("main")
            or soup.find(attrs={"role": "main"})
            or soup.find("article")
            or soup.find(id=re.compile(r"content|main", re.IGNORECASE))
            or soup
        )

        items: list[Item] = []
        for link in root.find_all("a", href=True):
            href = link["href"].strip()
            title = link.get_text(" ", strip=True)
            if not href or not title or len(title) < 8:
                continue
            if href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            if _SKIP_RE.search(title) or _SKIP_RE.search(href):
                continue

            abs_url = urljoin(base + "/", href)
            # Only keep links that stay on the source's own site and point at a
            # real sub-page (not the listing page itself).
            if urlparse(abs_url).netloc != urlparse(base).netloc:
                continue
            if abs_url.rstrip("/") in (url.rstrip("/"), base.rstrip("/")):
                continue
            if abs_url in seen:
                continue
            seen.add(abs_url)

            # Date from the link text or its surrounding block.
            container = link.find_parent(["li", "article", "div", "tr", "p"])
            ctx = container.get_text(" ", strip=True) if container else title
            date = _extract_date(title, ctx)

            uid = hashlib.md5(abs_url.encode()).hexdigest()[:12]
            items.append(Item(
                id=uid,
                title=title[:140],
                description=ctx[:400] if ctx and ctx != title else title[:400],
                date=date,
                category=category,
                url=abs_url,
                data={"source": source, "local": local},
            ))
        return items
