"""Events from Barn Theatre Oxted, Master Park, and community submissions."""
import hashlib
import json
import httpx
from bs4 import BeautifulSoup
from pathlib import Path
from .base import BaseCollector, CollectionResult, Item, now_iso

BARN_THEATRE_URL = "https://barntheatre.org.uk/whats-on"
MASTER_PARK_URL = "https://www.masterpark.co.uk/events"
SUBMISSIONS_DIR = Path("data/events/approved")


class EventsCollector(BaseCollector):
    name = "events"

    def collect(self) -> CollectionResult:
        items: list[Item] = []
        items.extend(self._fetch_barn_theatre())
        items.extend(self._fetch_master_park())
        items.extend(self._load_approved_submissions())
        items.sort(key=lambda x: x.date)
        return CollectionResult(source=self.name, collected_at=now_iso(), items=items[:50])

    def _fetch_barn_theatre(self) -> list[Item]:
        try:
            resp = httpx.get(BARN_THEATRE_URL, timeout=20, follow_redirects=True)
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as exc:
            print(f"[events] Barn Theatre fetch failed: {exc}")
            return []

        items = []
        # Barn Theatre typically lists events in article/li elements
        for el in soup.select("article, .event, li.event-item, .tribe-event")[:20]:
            title_el = el.select_one("h2, h3, .title, .event-title")
            date_el = el.select_one("time, .date, .event-date")
            link_el = el.select_one("a[href]")

            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue
            date_str = (date_el.get("datetime", "") or date_el.get_text(strip=True)
                        if date_el else now_iso()[:10])
            if len(date_str) > 10:
                date_str = date_str[:10]
            href = link_el["href"] if link_el else BARN_THEATRE_URL
            if href and not href.startswith("http"):
                href = "https://barntheatre.org.uk" + href

            uid = hashlib.md5(f"barn{title}{date_str}".encode()).hexdigest()[:12]
            items.append(Item(
                id=uid,
                title=title,
                description=f"At the Barn Theatre, Oxted. {date_str}.",
                date=date_str,
                category="events",
                url=href,
                data={"venue": "Barn Theatre, Oxted"},
            ))
        return items

    def _fetch_master_park(self) -> list[Item]:
        try:
            resp = httpx.get(MASTER_PARK_URL, timeout=20, follow_redirects=True)
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as exc:
            print(f"[events] Master Park fetch failed: {exc}")
            return []

        items = []
        for el in soup.select("article, .event, .tribe-event, li.event")[:15]:
            title_el = el.select_one("h2, h3, .title")
            date_el = el.select_one("time, .date")
            link_el = el.select_one("a[href]")

            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue
            date_str = (date_el.get("datetime", "")[:10] if date_el and date_el.get("datetime")
                        else now_iso()[:10])
            href = link_el["href"] if link_el else MASTER_PARK_URL

            uid = hashlib.md5(f"masterpark{title}{date_str}".encode()).hexdigest()[:12]
            items.append(Item(
                id=uid,
                title=title,
                description=f"At Master Park, Oxted. {date_str}.",
                date=date_str,
                category="events",
                url=href,
                data={"venue": "Master Park, Oxted"},
            ))
        return items

    def _load_approved_submissions(self) -> list[Item]:
        items = []
        SUBMISSIONS_DIR.mkdir(parents=True, exist_ok=True)
        for path in sorted(SUBMISSIONS_DIR.glob("*.json")):
            try:
                raw = json.loads(path.read_text())
                items.append(Item(
                    id=raw.get("id", path.stem),
                    title=raw["title"],
                    description=raw.get("description", ""),
                    date=raw.get("date", now_iso()[:10]),
                    category="events",
                    url=raw.get("url", ""),
                    data={**raw, "source": "community"},
                ))
            except Exception as exc:
                print(f"[events] bad submission {path.name}: {exc}")
        return items
