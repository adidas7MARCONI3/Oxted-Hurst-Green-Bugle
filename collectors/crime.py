"""Crime data from data.police.uk — no API key required."""
import hashlib
import httpx
from .base import BaseCollector, CollectionResult, Item, now_iso

# Oxted town centre approx
OXTED_LAT = 51.2572
OXTED_LNG = -0.0043
RADIUS_MILES = 2


class CrimeCollector(BaseCollector):
    name = "crime"
    API = "https://data.police.uk/api"

    def collect(self) -> CollectionResult:
        items = []
        try:
            resp = httpx.get(
                f"{self.API}/crimes-street/all-crime",
                params={"lat": OXTED_LAT, "lng": OXTED_LNG},
                timeout=30,
            )
            resp.raise_for_status()
            crimes = resp.json()
        except Exception as exc:
            print(f"[crime] fetch failed: {exc}")
            crimes = []

        for c in crimes:
            uid = c.get("id") or hashlib.md5(str(c).encode()).hexdigest()[:12]
            category = c.get("category", "unknown").replace("-", " ").title()
            location = c.get("location", {})
            street = location.get("street", {}).get("name", "unknown location")
            outcome = c.get("outcome_status")
            outcome_str = outcome["category"] if outcome else "under investigation"
            items.append(Item(
                id=str(uid),
                title=f"{category} – {street.title()}",
                description=f"{category} reported on {street.title()}. Status: {outcome_str}.",
                date=c.get("month", now_iso()[:7]),
                category="crime",
                url=f"https://www.police.uk/pu/your-area/surrey-police/",
                data=c,
            ))

        # Sort newest first (months are YYYY-MM strings)
        items.sort(key=lambda x: x.date, reverse=True)
        return CollectionResult(source=self.name, collected_at=now_iso(), items=items[:30])
