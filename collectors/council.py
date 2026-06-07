"""Tandridge District Council news and decisions scraper."""
import hashlib
import httpx
import feedparser
from bs4 import BeautifulSoup
from .base import BaseCollector, CollectionResult, Item, now_iso

NEWS_RSS = "https://www.tandridge.gov.uk/rss/news"
DECISIONS_URL = "https://www.tandridge.gov.uk/Your-council/About-the-council/Council-meetings/Decisions-notices"


class CouncilCollector(BaseCollector):
    name = "council"

    def collect(self) -> CollectionResult:
        items: list[Item] = []
        items.extend(self._fetch_rss())
        items.extend(self._fetch_decisions())
        items.sort(key=lambda x: x.date, reverse=True)
        return CollectionResult(source=self.name, collected_at=now_iso(), items=items[:30])

    def _fetch_rss(self) -> list[Item]:
        try:
            feed = feedparser.parse(NEWS_RSS)
        except Exception as exc:
            print(f"[council] RSS failed: {exc}")
            return []
        result = []
        for entry in feed.entries[:20]:
            uid = hashlib.md5(entry.get("link", entry.get("title", "")).encode()).hexdigest()[:12]
            pub = entry.get("published", now_iso()[:10])
            # feedparser gives struct_time; convert to ISO
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                from datetime import datetime, timezone
                pub = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).strftime("%Y-%m-%d")
            result.append(Item(
                id=uid,
                title=entry.get("title", "Council news"),
                description=BeautifulSoup(entry.get("summary", ""), "html.parser").get_text()[:400],
                date=pub,
                category="council",
                url=entry.get("link", "https://www.tandridge.gov.uk"),
                data={"source": "rss"},
            ))
        return result

    def _fetch_decisions(self) -> list[Item]:
        try:
            resp = httpx.get(DECISIONS_URL, timeout=20, follow_redirects=True)
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as exc:
            print(f"[council] decisions fetch failed: {exc}")
            return []

        items = []
        for link in soup.select("a[href*='Decision']")[:10]:
            href = link.get("href", "")
            if not href.startswith("http"):
                href = "https://www.tandridge.gov.uk" + href
            title = link.get_text(strip=True) or "Council decision"
            uid = hashlib.md5(href.encode()).hexdigest()[:12]
            items.append(Item(
                id=uid,
                title=title,
                description=f"Tandridge District Council decision notice. See link for full details.",
                date=now_iso()[:10],
                category="council",
                url=href,
                data={"source": "decisions"},
            ))
        return items
