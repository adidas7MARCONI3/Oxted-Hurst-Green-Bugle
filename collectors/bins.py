"""Bin collection days from Tandridge District Council.

Tandridge exposes collection data via a public API used by their web checker.
Set BINS_UPRN in .env (your Unique Property Reference Number — find at
https://www.tandridge.gov.uk/rubbish-and-recycling/when-is-my-collection-day).
"""
import os
import hashlib
import httpx
from bs4 import BeautifulSoup
from .base import BaseCollector, CollectionResult, Item, now_iso

CHECKER_URL = "https://www.tandridge.gov.uk/rubbish-and-recycling/when-is-my-collection-day"
# The underlying Alloy/Yotta API that Tandridge's page calls:
ALLOY_API = "https://tandridge.gov.uk/umbraco/api/CollectionDayApi/GetCollectionDays"


class BinsCollector(BaseCollector):
    name = "bins"

    def __init__(self):
        self.uprn = os.getenv("BINS_UPRN", "")

    def collect(self) -> CollectionResult:
        if not self.uprn:
            print("[bins] BINS_UPRN not set — skipping")
            return CollectionResult(source=self.name, collected_at=now_iso(), items=[])

        items = self._fetch_alloy() or self._fetch_scrape()
        return CollectionResult(source=self.name, collected_at=now_iso(), items=items)

    def _fetch_alloy(self) -> list[Item]:
        try:
            resp = httpx.get(
                ALLOY_API,
                params={"uprn": self.uprn},
                timeout=15,
                follow_redirects=True,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            print(f"[bins] Alloy API failed: {exc}")
            return []

        items = []
        for collection in data if isinstance(data, list) else data.get("collections", []):
            bin_type = collection.get("type", collection.get("name", "Collection"))
            date_str = collection.get("date", collection.get("nextCollection", now_iso()[:10]))
            if len(date_str) > 10:
                date_str = date_str[:10]
            uid = hashlib.md5(f"{self.uprn}{bin_type}{date_str}".encode()).hexdigest()[:12]
            items.append(Item(
                id=uid,
                title=f"{bin_type} collection — {date_str}",
                description=f"Your {bin_type.lower()} bin is collected on {date_str}.",
                date=date_str,
                category="bins",
                url="https://www.tandridge.gov.uk/rubbish-and-recycling/when-is-my-collection-day",
                data=collection,
            ))
        return items

    def _fetch_scrape(self) -> list[Item]:
        """Fallback: POST UPRN to the web form and scrape the result."""
        try:
            session = httpx.Client(follow_redirects=True, timeout=20)
            page = session.get(CHECKER_URL)
            soup = BeautifulSoup(page.text, "html.parser")
            token = ""
            token_input = soup.find("input", {"name": "__RequestVerificationToken"})
            if token_input:
                token = token_input.get("value", "")

            resp = session.post(
                CHECKER_URL,
                data={"uprn": self.uprn, "__RequestVerificationToken": token},
            )
            soup2 = BeautifulSoup(resp.text, "html.parser")
        except Exception as exc:
            print(f"[bins] scrape failed: {exc}")
            return []

        items = []
        for row in soup2.select(".collection-day, .bin-day, tr"):
            cells = [td.get_text(strip=True) for td in row.select("td")]
            if len(cells) >= 2:
                bin_type, date_str = cells[0], cells[1]
                uid = hashlib.md5(f"{bin_type}{date_str}".encode()).hexdigest()[:12]
                items.append(Item(
                    id=uid,
                    title=f"{bin_type} collection — {date_str}",
                    description=f"Your {bin_type.lower()} bin is collected on {date_str}.",
                    date=now_iso()[:10],
                    category="bins",
                    url=CHECKER_URL,
                    data={"type": bin_type, "date": date_str},
                ))
        return items
