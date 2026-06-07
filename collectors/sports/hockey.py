"""Hockey results from England Hockey / GMS.
import re

Set HOCKEY_CLUB_NAME (e.g. "Oxted HC") in .env.
England Hockey club pages follow the pattern:
https://www.englandhockey.co.uk/clubs/<slug>
GMS (the results system) is at gms.englandhockey.co.uk
"""
import os
import hashlib
import httpx
from bs4 import BeautifulSoup
from ..base import BaseCollector, CollectionResult, Item, now_iso

GMS_BASE = "https://gms.englandhockey.co.uk"
CLUB_SEARCH = f"{GMS_BASE}/clubs/search"


class HockeyCollector(BaseCollector):
    name = "hockey"

    def __init__(self):
        self.club_name = os.getenv("HOCKEY_CLUB_NAME", "Oxted")
        self.club_id = os.getenv("HOCKEY_CLUB_ID", "")

    def collect(self) -> CollectionResult:
        items: list[Item] = []
        try:
            if not self.club_id:
                self.club_id = self._find_club_id()
            if self.club_id:
                items = self._fetch_fixtures()
        except Exception as exc:
            print(f"[hockey] fetch failed: {exc}")
        return CollectionResult(source=self.name, collected_at=now_iso(), items=items[:20])

    def _find_club_id(self) -> str:
        try:
            resp = httpx.get(
                CLUB_SEARCH,
                params={"name": self.club_name},
                timeout=15,
                follow_redirects=True,
            )
            soup = BeautifulSoup(resp.text, "html.parser")
            link = soup.select_one("a[href*='/clubs/']")
            if link:
                parts = link["href"].split("/")
                return parts[-1] if parts else ""
        except Exception:
            pass
        return ""

    def _fetch_fixtures(self) -> list[Item]:
        resp = httpx.get(
            f"{GMS_BASE}/clubs/{self.club_id}/fixtures",
            timeout=15,
            follow_redirects=True,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        items = []
        for row in soup.select("tr.fixture-row, .fixture, tr[data-fixture]")[:20]:
            cells = row.select("td")
            if len(cells) < 3:
                continue
            home = cells[0].get_text(strip=True) if cells else ""
            score = cells[1].get_text(strip=True) if len(cells) > 1 else "v"
            away = cells[2].get_text(strip=True) if len(cells) > 2 else ""
            date_el = row.select_one("time, .date")
            date_str = (date_el.get("datetime", "")[:10]
                        if date_el and date_el.get("datetime")
                        else now_iso()[:10])
            if not home or not away:
                continue

            is_result = re.match(r"\d+\s*-\s*\d+", score) if __import__("re").match(r"\d", score[:1]) else False
            category = "hockey_result" if is_result else "hockey_fixture"
            uid = hashlib.md5(f"{home}{away}{date_str}".encode()).hexdigest()[:12]
            items.append(Item(
                id=uid,
                title=f"{home} {score} {away}",
                description=f"Hockey {'result' if is_result else 'fixture'}: "
                            f"{home} {'beat' if is_result else 'v'} {away} ({date_str}).",
                date=date_str,
                category=category,
                url=f"{GMS_BASE}/clubs/{self.club_id}/fixtures",
                data={"home": home, "away": away, "score": score},
            ))
        return items
