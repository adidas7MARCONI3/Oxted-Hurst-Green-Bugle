"""Football results from FA Full-Time (fulltime.thefa.com).

Set FA_CLUB_NAME to match how the club appears on Full-Time,
e.g. "Oxted & District FC". FA_COMPETITION_ID narrows the search.
"""
import os
import re
import hashlib
import httpx
from bs4 import BeautifulSoup
from ..base import BaseCollector, CollectionResult, Item, now_iso

FULLTIME_BASE = "https://fulltime.thefa.com"
RESULTS_PATH = "/results.html"


class FootballCollector(BaseCollector):
    name = "football"

    def __init__(self):
        self.club_name = os.getenv("FA_CLUB_NAME", "Oxted")
        self.competition_id = os.getenv("FA_COMPETITION_ID", "")

    def collect(self) -> CollectionResult:
        items: list[Item] = []
        try:
            items = self._scrape_results()
        except Exception as exc:
            print(f"[football] scrape failed: {exc}")
        return CollectionResult(source=self.name, collected_at=now_iso(), items=items[:20])

    def _scrape_results(self) -> list[Item]:
        params = {"selectedSeason": "2024-2025"}
        if self.competition_id:
            params["selectedCompetition"] = self.competition_id
        resp = httpx.get(
            f"{FULLTIME_BASE}{RESULTS_PATH}",
            params=params,
            timeout=20,
            follow_redirects=True,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        items = []

        for row in soup.select("tr.result-row, .match-row, table.results tr"):
            cells = row.select("td")
            if len(cells) < 3:
                continue
            text = " ".join(c.get_text(" ", strip=True) for c in cells)
            if self.club_name.lower() not in text.lower():
                continue

            # Try to parse: home SCORE away DATE
            home_el = row.select_one(".home-team, td:nth-child(1)")
            away_el = row.select_one(".away-team, td:nth-child(3)")
            score_el = row.select_one(".score, td:nth-child(2)")
            date_el = row.select_one(".date, time, td:nth-child(4)")

            home = home_el.get_text(strip=True) if home_el else ""
            away = away_el.get_text(strip=True) if away_el else ""
            score = score_el.get_text(strip=True) if score_el else "v"
            date_str = date_el.get_text(strip=True) if date_el else now_iso()[:10]

            if not home or not away:
                continue

            uid = hashlib.md5(f"{home}{away}{score}{date_str}".encode()).hexdigest()[:12]
            items.append(Item(
                id=uid,
                title=f"{home} {score} {away}",
                description=f"Football result: {home} {score} {away} ({date_str}).",
                date=now_iso()[:10],
                category="football",
                url=resp.url.__str__(),
                data={"home": home, "away": away, "score": score, "date": date_str},
            ))
        return items
