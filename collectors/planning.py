"""Planning applications from planning.data.gov.uk + Tandridge DC."""
import hashlib
import httpx
from .base import BaseCollector, CollectionResult, Item, now_iso

TANDRIDGE_LPA = "tandridge"  # planning.data.gov.uk slug
GEOMETRY_WKT = "POINT(-0.0043 51.2572)"  # Oxted


class PlanningCollector(BaseCollector):
    name = "planning"
    API = "https://www.planning.data.gov.uk/api/v1"

    def collect(self) -> CollectionResult:
        items = []
        try:
            resp = httpx.get(
                f"{self.API}/entity.json",
                params={
                    "dataset": "planning-application",
                    "organisation": f"local-authority:{TANDRIDGE_LPA}",
                    "limit": 50,
                    "entries": "current",
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            applications = data.get("entities", [])
        except Exception as exc:
            print(f"[planning] planning.data.gov.uk failed: {exc}")
            applications = []

        for app in applications:
            ref = app.get("reference", "")
            uid = hashlib.md5(ref.encode()).hexdigest()[:12] if ref else str(app.get("entity", ""))
            address = app.get("name", app.get("address-text", "unknown address"))
            description = app.get("description", "No description available.")
            status = app.get("development-type", "unknown")
            entry_date = app.get("entry-date", now_iso()[:10])
            app_url = f"https://www.planning.data.gov.uk/entity/{app.get('entity', '')}"
            items.append(Item(
                id=uid,
                title=f"{ref} — {address[:60]}",
                description=f"{description[:300]} [{status}]",
                date=entry_date,
                category="planning",
                url=app_url,
                data={k: v for k, v in app.items() if k not in ("geometry",)},
            ))

        items.sort(key=lambda x: x.date, reverse=True)
        return CollectionResult(source=self.name, collected_at=now_iso(), items=items[:25])
