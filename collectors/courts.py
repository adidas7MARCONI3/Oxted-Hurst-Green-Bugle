"""Court listings for Reigate and Redhill Magistrates (nearest to Oxted).

Scrapes the judiciary.gov.uk daily court list — no API key required.
"""
import re
import hashlib
import httpx
from bs4 import BeautifulSoup
from datetime import date
from .base import BaseCollector, CollectionResult, Item, now_iso

# Reigate Magistrates Court (closes 2024 → Guildford/Redhill used instead)
# We scrape court lists from judiciary.gov.uk
SEARCH_URL = "https://www.judiciary.gov.uk/courts-and-offices/"
DAILY_LIST_API = "https://www.gov.uk/government/publications?keywords=daily+court+list+surrey"


class CourtsCollector(BaseCollector):
    name = "courts"

    def collect(self) -> CollectionResult:
        items = []
        try:
            items = self._fetch_gov_listings()
        except Exception as exc:
            print(f"[courts] fetch failed: {exc}")

        return CollectionResult(source=self.name, collected_at=now_iso(), items=items[:20])

    def _fetch_gov_listings(self) -> list[Item]:
        resp = httpx.get(
            "https://www.gov.uk/government/publications",
            params={
                "keywords": "court list surrey",
                "publication_filter_option": "transparency-data",
                "departments[]": "hm-courts-and-tribunals-service",
            },
            timeout=20,
            follow_redirects=True,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        results = soup.select("li.gem-c-document-list__item")
        items = []
        for r in results[:20]:
            link_tag = r.select_one("a")
            if not link_tag:
                continue
            title = link_tag.get_text(strip=True)
            href = "https://www.gov.uk" + link_tag.get("href", "")
            date_tag = r.select_one("time")
            pub_date = date_tag["datetime"][:10] if date_tag and date_tag.get("datetime") else now_iso()[:10]
            uid = hashlib.md5(href.encode()).hexdigest()[:12]
            items.append(Item(
                id=uid,
                title=title,
                description=f"Court listing published {pub_date}. See link for full schedule.",
                date=pub_date,
                category="courts",
                url=href,
                data={"title": title, "url": href},
            ))
        return items
