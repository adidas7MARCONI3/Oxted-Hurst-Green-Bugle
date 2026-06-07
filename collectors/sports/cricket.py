"""Cricket results from Play-Cricket API.

Register at https://play-cricket.com/api to get a free API key.
Set PLAY_CRICKET_API_KEY and PLAY_CRICKET_SITE_ID in .env.

PLAY_CRICKET_SITE_ID for Oxted CC can be found on the club's Play-Cricket page URL.
"""
import os
import hashlib
import httpx
from ..base import BaseCollector, CollectionResult, Item, now_iso

API_BASE = "https://play-cricket.com/api/v2"


class CricketCollector(BaseCollector):
    name = "cricket"

    def __init__(self):
        self.api_key = os.getenv("PLAY_CRICKET_API_KEY", "")
        self.site_id = os.getenv("PLAY_CRICKET_SITE_ID", "")

    def collect(self) -> CollectionResult:
        if not self.api_key or not self.site_id:
            print("[cricket] PLAY_CRICKET_API_KEY or PLAY_CRICKET_SITE_ID not set — skipping")
            return CollectionResult(source=self.name, collected_at=now_iso(), items=[])

        items: list[Item] = []
        try:
            items.extend(self._fetch_results())
            items.extend(self._fetch_fixtures())
        except Exception as exc:
            print(f"[cricket] fetch failed: {exc}")

        items.sort(key=lambda x: x.date, reverse=True)
        return CollectionResult(source=self.name, collected_at=now_iso(), items=items[:20])

    def _fetch_results(self) -> list[Item]:
        resp = httpx.get(
            f"{API_BASE}/matches.json",
            params={"api_token": self.api_key, "site_id": self.site_id,
                    "season": "2025", "type": "result"},
            timeout=20,
        )
        resp.raise_for_status()
        matches = resp.json().get("matches", [])
        items = []
        for m in matches[:15]:
            home = m.get("home_club_name", "")
            away = m.get("away_club_name", "")
            result = m.get("result_description", "Match played")
            date_str = (m.get("match_date", now_iso()[:10]) or "")[:10]
            comp = m.get("competition_name", "Cricket")
            uid = hashlib.md5(f"{m.get('id', home+away+date_str)}".encode()).hexdigest()[:12]
            items.append(Item(
                id=uid,
                title=f"{home} v {away}: {result}",
                description=f"{comp}. {home} hosted {away}. Result: {result}.",
                date=date_str,
                category="cricket",
                url=f"https://play-cricket.com/matches/{m.get('id', '')}",
                data=m,
            ))
        return items

    def _fetch_fixtures(self) -> list[Item]:
        resp = httpx.get(
            f"{API_BASE}/matches.json",
            params={"api_token": self.api_key, "site_id": self.site_id,
                    "season": "2025", "type": "fixture"},
            timeout=20,
        )
        resp.raise_for_status()
        matches = resp.json().get("matches", [])
        items = []
        for m in matches[:5]:
            home = m.get("home_club_name", "")
            away = m.get("away_club_name", "")
            date_str = (m.get("match_date", now_iso()[:10]) or "")[:10]
            comp = m.get("competition_name", "Cricket")
            uid = hashlib.md5(f"fix{m.get('id', home+away+date_str)}".encode()).hexdigest()[:12]
            items.append(Item(
                id=uid,
                title=f"Fixture: {home} v {away}",
                description=f"Upcoming {comp} match: {home} v {away} on {date_str}.",
                date=date_str,
                category="cricket",
                url=f"https://play-cricket.com/matches/{m.get('id', '')}",
                data=m,
            ))
        return items
