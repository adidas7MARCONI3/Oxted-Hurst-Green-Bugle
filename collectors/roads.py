"""Road closures and roadworks affecting Oxted & Hurst Green (RH8).

Two sources, no API keys required:

  1. Street Manager (primary) — the official UK government street works register
     operated by the DfT. The experimental open-data activities endpoint accepts
     a point + radius and returns planned roadworks, road closures and utility
     works:
       https://api.streetmanager.dft.gov.uk/experimental/activities
     Filtered to a 3 km radius of Oxted town centre (51.2567, -0.0049).

  2. Surrey County Council weekly highways bulletin (secondary) — the highway
     authority for the area. Their "roadworks in your area" page is scraped and
     filtered to the Tandridge district:
       https://www.surreycc.gov.uk/roads-and-transport/roadworks-and-maintenance/roadworks/in-your-area

Both sources fail gracefully: if one is unreachable the collector still returns
whatever the other produced. Results are de-duplicated by road + work type and
sorted with current/soonest works first.
"""
import hashlib
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from .base import BaseCollector, CollectionResult, Item, now_iso

# Street Manager experimental activities endpoint (no key required)
STREET_MANAGER_API = "https://api.streetmanager.dft.gov.uk/experimental/activities"

# Oxted town centre — search a 3 km radius around it
AREA_LAT = 51.2567
AREA_LONG = -0.0049
AREA_RADIUS_M = 3000

# Surrey CC weekly highways bulletin (Tandridge filtered)
SURREY_ROADWORKS_URL = (
    "https://www.surreycc.gov.uk/roads-and-transport/roadworks-and-maintenance/"
    "roadworks/in-your-area"
)

# Terms that mark a record as relevant to Oxted / Hurst Green / Tandridge.
LOCAL_TERMS = {
    "oxted", "hurst green", "limpsfield", "tandridge", "titsey",
    "rh8", "godstone", "woldingham",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.5",
}


def _parse_date(text: str) -> str:
    """Best-effort parse of a date string to YYYY-MM-DD; falls back to today."""
    text = (text or "").strip()
    if not text:
        return now_iso()[:10]
    # ISO timestamps (Street Manager): "2026-06-10T00:00:00.000Z"
    if re.match(r"\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    for fmt in ("%d %B %Y", "%d %b %Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return now_iso()[:10]


def _is_local(*fields: str) -> bool:
    """True if any local term appears in the supplied text fields."""
    blob = " ".join(f or "" for f in fields).lower()
    return any(term in blob for term in LOCAL_TERMS)


class RoadsCollector(BaseCollector):
    name = "roads"

    def collect(self) -> CollectionResult:
        seen: set[str] = set()
        items: list[Item] = []

        # Primary: Street Manager
        try:
            items.extend(self._fetch_street_manager(seen))
        except Exception as exc:
            print(f"[roads] Street Manager API failed: {exc}")

        # Secondary: Surrey CC weekly bulletin
        try:
            items.extend(self._fetch_surrey(seen))
        except Exception as exc:
            print(f"[roads] Surrey CC bulletin failed: {exc}")

        # Sort current/soonest first by start date (works without an explicit
        # start date sort to the end).
        items.sort(key=lambda x: x.data.get("start_date") or "9999-12-31")
        return CollectionResult(source=self.name, collected_at=now_iso(), items=items[:30])

    # ------------------------------------------------------------------
    # Primary: Street Manager experimental activities API
    # ------------------------------------------------------------------

    def _fetch_street_manager(self, seen: set[str]) -> list[Item]:
        resp = httpx.get(
            STREET_MANAGER_API,
            params={
                "latitude": AREA_LAT,
                "longitude": AREA_LONG,
                "radius": AREA_RADIUS_M,
            },
            headers=_HEADERS,
            timeout=30,
            follow_redirects=True,
        )
        resp.raise_for_status()
        payload = resp.json()

        # The endpoint may return either a bare list or an envelope object.
        if isinstance(payload, dict):
            activities = (
                payload.get("activities")
                or payload.get("results")
                or payload.get("items")
                or []
            )
        else:
            activities = payload

        items: list[Item] = []
        for act in activities:
            if not isinstance(act, dict):
                continue

            road = (
                act.get("street_name")
                or act.get("streetName")
                or act.get("usrn_street")
                or act.get("location_description")
                or act.get("locationDescription")
                or "Unnamed road"
            )
            town = act.get("town") or act.get("area_name") or act.get("areaName") or ""

            work_type = (
                act.get("activity_type")
                or act.get("activityType")
                or act.get("work_category")
                or act.get("works_category")
                or "Roadworks"
            )
            promoter = (
                act.get("promoter_organisation")
                or act.get("promoterOrganisation")
                or act.get("highway_authority")
                or act.get("highwayAuthority")
                or "Unknown promoter"
            )
            closure = (
                act.get("traffic_management_type")
                or act.get("trafficManagementType")
                or act.get("activity_type_details")
                or ""
            )

            start_raw = (
                act.get("start_date")
                or act.get("startDate")
                or act.get("proposed_start_date")
                or act.get("actual_start_date_time")
                or ""
            )
            end_raw = (
                act.get("end_date")
                or act.get("endDate")
                or act.get("proposed_end_date")
                or act.get("actual_end_date_time")
                or ""
            )
            start_date = _parse_date(str(start_raw)) if start_raw else ""
            end_date = _parse_date(str(end_raw)) if end_raw else ""

            ref = (
                act.get("work_reference_number")
                or act.get("workReferenceNumber")
                or act.get("activity_reference_number")
                or act.get("permit_reference_number")
                or f"{road}{start_date}"
            )
            if ref in seen:
                continue
            seen.add(ref)

            # Street Manager provides a public works summary page per reference.
            url = (
                f"https://www.streetmanager.service.gov.uk/works/{ref}"
                if re.match(r"^[A-Za-z]{2}\d", str(ref))
                else "https://www.streetmanager.service.gov.uk/"
            )

            road_label = f"{road}, {town}".strip(", ") if town else road
            tm = f" ({closure})" if closure else ""
            description_bits = [f"{work_type}{tm} on {road_label} by {promoter}."]
            if start_date and end_date:
                description_bits.append(f"Scheduled {start_date} to {end_date}.")
            elif start_date:
                description_bits.append(f"From {start_date}.")

            uid = hashlib.md5(str(ref).encode()).hexdigest()[:12]
            items.append(Item(
                id=uid,
                title=f"{road_label} — {work_type}",
                description=" ".join(description_bits)[:400],
                date=start_date or now_iso()[:10],
                category="roads",
                url=url,
                data={
                    "road": road_label,
                    "work_type": work_type,
                    "promoter": promoter,
                    "start_date": start_date,
                    "end_date": end_date,
                    "traffic_management": closure,
                    "reference": str(ref),
                    "source": "street_manager",
                },
            ))

        return items

    # ------------------------------------------------------------------
    # Secondary: Surrey CC weekly highways bulletin (Tandridge filtered)
    # ------------------------------------------------------------------

    def _fetch_surrey(self, seen: set[str]) -> list[Item]:
        resp = httpx.get(
            SURREY_ROADWORKS_URL,
            headers=_HEADERS,
            timeout=30,
            follow_redirects=True,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        items: list[Item] = []

        # The bulletin is rendered as a table of works; be lenient about the
        # exact structure and also accept definition/list style markup.
        rows = soup.select("table tr")
        for row in rows:
            cells = [c.get_text(separator=" ", strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            # Skip header rows
            if cells[0].lower() in {"road", "location", "street", "area"}:
                continue

            road = cells[0]
            description = " ".join(cells[1:])
            if not _is_local(road, description):
                continue

            # Pull dates out of the row text where present.
            dates = re.findall(r"\d{1,2}[/ -][A-Za-z0-9]{2,9}[/ -]\d{2,4}", description)
            start_date = _parse_date(dates[0]) if dates else ""
            end_date = _parse_date(dates[1]) if len(dates) > 1 else ""

            ref = f"surrey:{road}:{start_date}"
            if ref in seen:
                continue
            seen.add(ref)

            link = row.find("a", href=True)
            url = link["href"] if link else SURREY_ROADWORKS_URL
            if url.startswith("/"):
                url = "https://www.surreycc.gov.uk" + url

            uid = hashlib.md5(ref.encode()).hexdigest()[:12]
            items.append(Item(
                id=uid,
                title=f"{road} — Surrey CC works",
                description=(f"{description} (Surrey County Council, Tandridge district).")[:400],
                date=start_date or now_iso()[:10],
                category="roads",
                url=url,
                data={
                    "road": road,
                    "work_type": "Highway works",
                    "promoter": "Surrey County Council",
                    "start_date": start_date,
                    "end_date": end_date,
                    "source": "surrey_cc",
                },
            ))

        return items
