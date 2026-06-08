"""Council news and meetings scraper.

Pulls three hyperlocal sources relevant to Oxted & Hurst Green residents:

  1. Tandridge District Council — News
     https://www.tandridge.gov.uk/Your-council/News
  2. Tandridge District Council — Meetings (agendas / committee meetings)
     https://www.tandridge.gov.uk/Your-council/Meetings-and-decisions/Meetings
  3. Oxted & Hurst Green Parish... — Oxted Parish Council meetings
     http://oxted-pc.org.uk/meetings/

Tandridge District Council is the local authority for Oxted and Hurst Green, so
its district-wide news and meetings are relevant to residents; Oxted Parish
Council items are inherently hyperlocal.

The pages are plain server-rendered HTML. The previous implementation relied on
an RSS feed (``/rss/news``) that no longer returns items and sent requests with
no browser ``User-Agent`` (Tandridge serves header-less clients an empty/blocked
page), which is why the collector returned 0 items. This version scrapes the
three listing pages directly with browser headers and resilient parsing.
"""
import hashlib
import re
import urllib.parse
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from .base import BaseCollector, CollectionResult, Item, now_iso

NEWS_URL = "https://www.tandridge.gov.uk/Your-council/News"
MEETINGS_URL = "https://www.tandridge.gov.uk/Your-council/Meetings-and-decisions/Meetings"
OXTED_PC_URL = "http://oxted-pc.org.uk/meetings/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

# Words that signal a real content link rather than site chrome (nav, search,
# cookie/privacy boilerplate, social, login, etc.).
_NAV_NOISE = re.compile(
    r"\b(cookie|privacy|accessibility|sitemap|terms|login|sign in|register|"
    r"search|skip to|home|contact us|facebook|twitter|instagram|youtube|"
    r"feedback|complaint|a to z|a-z|menu)\b",
    re.IGNORECASE,
)

# Oxted / Hurst Green relevance keywords (Oxted PC and Tandridge-wide items are
# kept regardless; this is used to gently prioritise/keep clearly local items).
_LOCAL = re.compile(r"\b(oxted|hurst green|limpsfield|tandridge)\b", re.IGNORECASE)

# Date patterns commonly seen in link text / surrounding markup.
_DATE_PATTERNS = [
    # 1 June 2026 / 01 Jun 2026 / 1st June 2026
    (re.compile(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{4})\b",
        re.IGNORECASE,
    ), "dmy"),
    # 2026-06-01
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
    # 01/06/2026 or 1/6/2026
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "uk"),
]

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_date(text: str) -> str | None:
    """Extract the first recognisable date from ``text`` → YYYY-MM-DD, else None."""
    if not text:
        return None
    for pattern, kind in _DATE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        try:
            if kind == "dmy":
                day, mon, year = int(m.group(1)), m.group(2)[:3].lower(), int(m.group(3))
                return datetime(year, _MONTHS[mon], day).strftime("%Y-%m-%d")
            if kind == "iso":
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
            if kind == "uk":
                return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).strftime("%Y-%m-%d")
        except (ValueError, KeyError):
            continue
    return None


class CouncilCollector(BaseCollector):
    name = "council"

    def collect(self) -> CollectionResult:
        items: list[Item] = []
        items.extend(self._safe(self._fetch_tandridge_news, "Tandridge news"))
        items.extend(self._safe(self._fetch_tandridge_meetings, "Tandridge meetings"))
        items.extend(self._safe(self._fetch_oxted_pc, "Oxted Parish Council"))

        # De-duplicate by URL, keeping the first (highest-priority) occurrence.
        seen: set[str] = set()
        deduped: list[Item] = []
        for item in items:
            if not item.url or item.url in seen:
                continue
            seen.add(item.url)
            deduped.append(item)

        deduped.sort(key=lambda x: x.date, reverse=True)
        return CollectionResult(source=self.name, collected_at=now_iso(), items=deduped[:30])

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe(fn, label: str) -> list[Item]:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - one bad source must not sink the rest
            print(f"[council] {label} failed: {exc}")
            return []

    @staticmethod
    def _get_soup(url: str) -> BeautifulSoup | None:
        resp = httpx.get(url, headers=_HEADERS, timeout=25, follow_redirects=True)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")

    @staticmethod
    def _content_root(soup: BeautifulSoup):
        """Return the main content node, falling back to the whole document."""
        for selector in ("main", "#content", "#main-content", "article", "[role=main]"):
            node = soup.select_one(selector)
            if node:
                return node
        return soup

    @staticmethod
    def _absolute(href: str, base: str) -> str:
        return urllib.parse.urljoin(base, href.strip())

    def _scrape_links(
        self,
        url: str,
        href_keywords: tuple[str, ...],
        source_tag: str,
        default_desc: str,
        limit: int = 20,
    ) -> list[Item]:
        """Generic listing scraper: collect content anchors whose href matches one
        of ``href_keywords``, turning each into an Item with a resolved URL and a
        best-effort date drawn from the link or its surrounding text."""
        soup = self._get_soup(url)
        if soup is None:
            return []
        root = self._content_root(soup)

        items: list[Item] = []
        seen: set[str] = set()
        for link in root.find_all("a", href=True):
            href = link["href"].strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            low_href = href.lower()
            if not any(kw in low_href for kw in href_keywords):
                continue

            title = " ".join(link.get_text(" ", strip=True).split())
            if len(title) < 5 or _NAV_NOISE.search(title):
                continue

            abs_url = self._absolute(href, url)
            if abs_url in seen or abs_url.rstrip("/") == url.rstrip("/"):
                continue
            seen.add(abs_url)

            # Look for a date in the link text, then in nearby markup.
            context = title
            parent = link.find_parent(["li", "article", "div", "tr", "td", "p"])
            if parent is not None:
                context = parent.get_text(" ", strip=True)
            date = _parse_date(title) or _parse_date(context) or now_iso()[:10]

            uid = hashlib.md5(abs_url.encode()).hexdigest()[:12]
            items.append(Item(
                id=uid,
                title=title[:140],
                description=default_desc,
                date=date,
                category="council",
                url=abs_url,
                data={"source": source_tag},
            ))
            if len(items) >= limit:
                break
        return items

    # ------------------------------------------------------------------
    # sources
    # ------------------------------------------------------------------

    def _fetch_tandridge_news(self) -> list[Item]:
        return self._scrape_links(
            NEWS_URL,
            href_keywords=("/news", "news/", "newsitem", "article"),
            source_tag="tandridge_news",
            default_desc=(
                "News from Tandridge District Council, the local authority for "
                "Oxted and Hurst Green. See link for the full story."
            ),
        )

    def _fetch_tandridge_meetings(self) -> list[Item]:
        return self._scrape_links(
            MEETINGS_URL,
            href_keywords=(
                "meeting", "committee", "agenda", "minutes",
                "ielistdocuments", "mglistplans", "decision",
            ),
            source_tag="tandridge_meetings",
            default_desc=(
                "Tandridge District Council meeting — agenda, papers or decisions. "
                "See link for full details."
            ),
        )

    def _fetch_oxted_pc(self) -> list[Item]:
        items = self._scrape_links(
            OXTED_PC_URL,
            href_keywords=(
                "meeting", "agenda", "minute", ".pdf", "/wp-content/",
                "uploads",
            ),
            source_tag="oxted_pc",
            default_desc=(
                "Oxted Parish Council meeting agenda or minutes. "
                "See link for full details."
            ),
        )
        # Everything from Oxted PC is hyperlocal; tag relevance explicitly.
        for item in items:
            item.data["local"] = True
        return items
