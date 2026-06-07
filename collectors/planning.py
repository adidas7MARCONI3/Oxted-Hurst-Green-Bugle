"""Planning applications from planning.data.gov.uk (primary) and the
Tandridge District Council planning portal (fallback scraper).

Primary source:
  https://www.planning.data.gov.uk/entity.json
  Filters: dataset=planning-application, organisation=local-authority:TAN
  Note: Tandridge has not yet published to the national dataset; this will
  return results once they do and acts as a future-proof primary path.

Fallback source:
  https://tdcplanningsearch.tandridge.gov.uk/
  ASP.NET WebForms portal. Three-step POST:
    1. GET root  → extract VIEWSTATE tokens
    2. POST dropdown change (Address) → updated VIEWSTATE + reveals text input
    3. POST search for 'Oxted' → parse results table
  Item URLs: PlanningApplicationDetail.aspx?ref={reference}
"""
import hashlib
import re
import urllib.parse
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from .base import BaseCollector, CollectionResult, Item, now_iso

PLANNING_API = "https://www.planning.data.gov.uk/entity.json"
PORTAL_ROOT = "https://tdcplanningsearch.tandridge.gov.uk/"
PORTAL_DETAIL = "https://tdcplanningsearch.tandridge.gov.uk/PlanningApplicationDetail.aspx"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.5",
}


def _parse_uk_date(text: str) -> str:
    """Convert 'DD Mon YYYY' or 'D Mon YYYY' to YYYY-MM-DD; return today on failure."""
    text = text.strip()
    if not text or text.lower() == "not yet determined":
        return now_iso()[:10]
    for fmt in ("%d %b %Y", "%-d %b %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return now_iso()[:10]


def _extract_hidden(html: str) -> dict[str, str]:
    """Return __VIEWSTATE, __VIEWSTATEGENERATOR, __EVENTVALIDATION from page HTML."""
    out = {}
    for field in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        m = re.search(
            rf'<input[^>]*name="{re.escape(field)}"[^>]*value="([^"]*)"',
            html,
        )
        out[field] = m.group(1) if m else ""
    return out


class PlanningCollector(BaseCollector):
    name = "planning"

    def collect(self) -> CollectionResult:
        seen_refs: set[str] = set()
        items: list[Item] = []

        # Primary: national planning dataset (future-proof once Tandridge publishes)
        try:
            items.extend(self._fetch_planning_api(seen_refs))
        except Exception as exc:
            print(f"[planning] planning.data.gov.uk failed: {exc}")

        # Fallback: Tandridge DC planning portal scraper
        if not items:
            try:
                items.extend(self._fetch_portal(seen_refs))
            except Exception as exc:
                print(f"[planning] Tandridge portal failed: {exc}")

        items.sort(key=lambda x: x.date, reverse=True)
        return CollectionResult(source=self.name, collected_at=now_iso(), items=items[:25])

    # ------------------------------------------------------------------
    # Primary: planning.data.gov.uk
    # ------------------------------------------------------------------

    def _fetch_planning_api(self, seen_refs: set[str]) -> list[Item]:
        resp = httpx.get(
            PLANNING_API,
            params={
                "dataset": "planning-application",
                "organisation": "local-authority:TAN",
                "limit": 100,
                "entries": "current",
            },
            timeout=30,
            follow_redirects=True,
        )
        resp.raise_for_status()
        entities = resp.json().get("entities", [])

        items = []
        for entity in entities:
            ref = entity.get("reference", "")
            if not ref or ref in seen_refs:
                continue
            seen_refs.add(ref)

            entity_id = entity.get("entity", "")
            url = f"https://www.planning.data.gov.uk/entity/{entity_id}" if entity_id else ""
            address = entity.get("name", entity.get("address-text", "Tandridge area"))
            description = entity.get("description", f"Planning application {ref}.")
            date_str = entity.get("entry-date", entity.get("start-date", now_iso()[:10]))[:10]

            uid = hashlib.md5(ref.encode()).hexdigest()[:12]
            items.append(Item(
                id=uid,
                title=f"{ref} — {address[:70]}",
                description=description[:400],
                date=date_str,
                category="planning",
                url=url,
                data={
                    "reference": ref,
                    "entity_id": entity_id,
                    "source": "planning_data_gov_uk",
                },
            ))

        return items

    # ------------------------------------------------------------------
    # Fallback: Tandridge DC portal (ASP.NET WebForms, 3-step POST)
    # ------------------------------------------------------------------

    def _fetch_portal(self, seen_refs: set[str]) -> list[Item]:
        with httpx.Client(
            headers=_HEADERS,
            follow_redirects=True,
            timeout=60,
        ) as client:
            # Step 1: GET homepage → VIEWSTATE tokens
            r1 = client.get(PORTAL_ROOT)
            r1.raise_for_status()
            h1 = _extract_hidden(r1.text)

            # Step 2: trigger dropdown postback (selects Address search type)
            # This causes the server to render the address text input field.
            r2 = client.post(
                PORTAL_ROOT,
                content=urllib.parse.urlencode({
                    "__EVENTTARGET": "ctl00$MainContent$ddlSearchCriteria",
                    "__EVENTARGUMENT": "",
                    "__LASTFOCUS": "",
                    "__VIEWSTATE": h1["__VIEWSTATE"],
                    "__VIEWSTATEGENERATOR": h1["__VIEWSTATEGENERATOR"],
                    "__EVENTVALIDATION": h1["__EVENTVALIDATION"],
                    "ctl00$MainContent$ddlSearchCriteria": "Address",
                }),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r2.raise_for_status()
            h2 = _extract_hidden(r2.text)

            # Step 3: submit search for "Oxted"
            r3 = client.post(
                PORTAL_ROOT,
                content=urllib.parse.urlencode({
                    "__EVENTTARGET": "",
                    "__EVENTARGUMENT": "",
                    "__LASTFOCUS": "",
                    "__VIEWSTATE": h2["__VIEWSTATE"],
                    "__VIEWSTATEGENERATOR": h2["__VIEWSTATEGENERATOR"],
                    "__EVENTVALIDATION": h2["__EVENTVALIDATION"],
                    "ctl00$MainContent$ddlSearchCriteria": "Address",
                    "ctl00$MainContent$txtAddress": "Oxted",
                    "ctl00$MainContent$txtSearchProposal": "",
                    "ctl00$MainContent$btnSearch": "Search",
                }),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r3.raise_for_status()

        return self._parse_portal_results(r3.text, seen_refs)

    def _parse_portal_results(self, html: str, seen_refs: set[str]) -> list[Item]:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if not table:
            return []

        rows = table.find_all("tr")[1:]  # skip header row
        items = []
        for row in rows:
            cols = [td.get_text(separator=" ", strip=True) for td in row.find_all("td")]
            if len(cols) < 2:
                continue

            # Columns: Application number, Address, Description, Parish,
            #          Comments until, Due date, Decision, Decision date
            ref = cols[0].strip()
            if not ref or ref in seen_refs:
                continue
            seen_refs.add(ref)

            address = cols[1] if len(cols) > 1 else ""
            description = cols[2] if len(cols) > 2 else ""
            decision = cols[6] if len(cols) > 6 else ""
            decision_date_raw = cols[7] if len(cols) > 7 else ""
            due_date_raw = cols[5] if len(cols) > 5 else ""

            date_str = _parse_uk_date(
                decision_date_raw
                if decision_date_raw and decision_date_raw.lower() != "not yet determined"
                else due_date_raw
            )

            url = f"{PORTAL_DETAIL}?ref={urllib.parse.quote(ref)}"

            status_suffix = f" [{decision}]" if decision and decision.lower() != "not yet determined" else ""
            uid = hashlib.md5(ref.encode()).hexdigest()[:12]
            items.append(Item(
                id=uid,
                title=f"{ref}: {address[:80]}{status_suffix}",
                description=description[:400] or f"Planning application for {address}.",
                date=date_str,
                category="planning",
                url=url,
                data={
                    "reference": ref,
                    "address": address,
                    "decision": decision,
                    "source": "tandridge_portal",
                },
            ))

        return items
