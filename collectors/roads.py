"""Road closures and roadworks affecting Oxted & Hurst Green (RH8).

Source: the DfT **Street Manager API v3** — the official UK government register
of street and road works.

    Base URL: https://api.streetmanager.dft.gov.uk/street-manager-api/v3
    Auth:     Bearer token in the STREET_MANAGER_API_KEY environment variable
    Works:    GET /works?latitude=51.2567&longitude=-0.0049&radius=3000
    Docs:     https://department-for-transport-streetmanager.github.io/
              street-manager-docs/api-documentation/

We query works within 3 km of Oxted town centre (lat 51.2567, long -0.0049) and
defensively re-filter on that radius when a record carries its own coordinates.

Each item carries, in `data`:

  * street_name            — the exact road affected
  * dates                  — "Mon 8 June – Fri 12 June" (start_date / end_date)
  * work_type              — Road closure / Lane closure / Traffic lights / …
  * promoter               — who is doing the work (Thames Water, BT Openreach …)
  * work_category          — Emergency / Minor / Standard / Major
  * status                 — Planned / In progress / Completed
  * traffic_management     — e.g. "Full road closure with diversion"
  * one_network_url        — deep link to one.network for the USRN
  * street_manager_url     — deep link to Street Manager public search

The description reads as a plain-English sentence, e.g.

    "Station Road West, Oxted will be closed from Mon 8 June to Fri 12 June for
     major utility works by Thames Water. Full road closure with diversion."

Items are sorted current/soonest-first.
"""
import hashlib
import math
import os
import re
from datetime import date
import httpx
from .base import BaseCollector, CollectionResult, Item, now_iso

STREET_MANAGER_API = "https://api.streetmanager.dft.gov.uk/street-manager-api/v3"
WORKS_ENDPOINT = f"{STREET_MANAGER_API}/works"

# Oxted town centre — Street Manager radius filter (3 km).
AREA_LAT = 51.2567
AREA_LONG = -0.0049
AREA_RADIUS_M = 3000

# Deep-link templates required by the brief.
ONE_NETWORK_USRN = "https://one.network/?USRN={usrn}"
STREET_MANAGER_PUBLIC = "https://streetmanager.dft.gov.uk/works/{ref}"


class RoadsCollector(BaseCollector):
    name = "roads"

    def __init__(self):
        self.api_key = os.getenv("STREET_MANAGER_API_KEY", "")

    def collect(self) -> CollectionResult:
        items: list[Item] = []
        if not self.api_key:
            print("[roads] STREET_MANAGER_API_KEY not set — skipping live data")
            return CollectionResult(source=self.name, collected_at=now_iso(), items=[])

        try:
            items = self._fetch_works()
        except Exception as exc:
            print(f"[roads] Street Manager API failed: {exc}")

        # Current/soonest-first: by start date ascending, blanks last.
        items.sort(key=lambda x: x.date or "9999-12-31")
        return CollectionResult(source=self.name, collected_at=now_iso(), items=items)

    # ── Street Manager v3 ─────────────────────────────────────────────────
    def _fetch_works(self) -> list[Item]:
        resp = httpx.get(
            WORKS_ENDPOINT,
            params={
                "latitude": AREA_LAT,
                "longitude": AREA_LONG,
                "radius": AREA_RADIUS_M,
            },
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            timeout=30,
        )
        resp.raise_for_status()
        records = _records(resp.json())

        items: list[Item] = []
        seen: set[str] = set()
        for rec in records:
            if not isinstance(rec, dict):
                continue
            if not _within_radius(rec):
                continue

            road = _field(rec, "street_name", "streetName", "road_name",
                          "roadName", "location_description",
                          "locationDescription", default="Unknown road")
            work_type = _field(rec, "work_type", "workType", "activity_type",
                               "activityType", "works_type",
                               default="Roadworks")
            promoter = _field(rec, "promoter_organisation",
                              "promoterOrganisation", "promoter",
                              "highway_authority", "highwayAuthority",
                              default="Highway authority")
            category = _normalise_category(
                _field(rec, "work_category", "workCategory", default="")
            )
            tm = _field(rec, "traffic_management_type", "trafficManagementType",
                        "traffic_management", default="")
            usrn = str(_field(rec, "usrn", "USRN", default="")).strip()
            ref = str(_field(rec, "work_reference_number", "workReferenceNumber",
                             "permit_reference_number",
                             default="")).strip()
            start = _iso_date(_field(rec, "proposed_start_date", "proposedStartDate",
                                     "start_date", "startDate",
                                     "actual_start_date_time"))
            end = _iso_date(_field(rec, "proposed_end_date", "proposedEndDate",
                                   "end_date", "endDate",
                                   "actual_end_date_time"))
            status = _normalise_status(
                _field(rec, "work_status", "workStatus", "status",
                       "work_status_ref", default=""),
                rec,
            )

            one_network_url = (ONE_NETWORK_USRN.format(usrn=usrn) if usrn
                               else "https://one.network/")
            street_manager_url = (STREET_MANAGER_PUBLIC.format(ref=ref) if ref
                                  else "https://streetmanager.dft.gov.uk/works")

            uid = hashlib.md5(f"sm{ref or usrn or road}{start}".encode()).hexdigest()[:12]
            if uid in seen:
                continue
            seen.add(uid)

            items.append(Item(
                id=uid,
                title=f"{work_type} — {road}",
                description=_summary(road, start, end, work_type, category,
                                     promoter, tm),
                date=start,
                category="roadworks",
                url=street_manager_url,
                data={
                    "road": road,
                    "street_name": road,
                    "usrn": usrn,
                    "work_reference_number": ref,
                    "work_type": work_type,
                    "work_category": category,
                    "status": status,
                    "traffic_management": tm,
                    "promoter": promoter,
                    "start_date": start,
                    "end_date": end,
                    "dates": _date_range(start, end),
                    "one_network_url": one_network_url,
                    "street_manager_url": street_manager_url,
                    "source": "Street Manager",
                },
            ))
        return items


# ── helpers ───────────────────────────────────────────────────────────────
def _records(payload) -> list:
    """Pull the list of works out of a bare list or a common envelope shape."""
    if isinstance(payload, dict):
        records = (payload.get("works") or payload.get("data")
                   or payload.get("items") or payload.get("results") or [])
    else:
        records = payload
    if isinstance(records, dict):
        records = [records]
    return records if isinstance(records, list) else []


def _field(rec: dict, *keys, default=""):
    for k in keys:
        if rec.get(k) not in (None, ""):
            return rec[k]
    return default


def _within_radius(rec: dict) -> bool:
    """Keep records inside the 3 km radius. The API already filters by radius,
    so a record without coordinates is trusted; one with coordinates is
    re-checked (defends against a looser server-side radius)."""
    lat = _coerce_float(_field(rec, "latitude", "lat", default=None))
    lng = _coerce_float(_field(rec, "longitude", "long", "lng", default=None))
    if lat is None or lng is None:
        return True
    return _haversine_m(AREA_LAT, AREA_LONG, lat, lng) <= AREA_RADIUS_M


def _coerce_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0  # Earth radius, metres
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def _normalise_category(raw: str) -> str:
    """Map Street Manager work categories onto Emergency / Minor / Standard /
    Major (Immediate works are urgent → Emergency)."""
    low = str(raw).lower()
    if "emergency" in low or "immediate" in low or "urgent" in low:
        return "Emergency"
    if "major" in low:
        return "Major"
    if "minor" in low:
        return "Minor"
    if "standard" in low:
        return "Standard"
    return raw or "Standard"


def _normalise_status(raw: str, rec: dict) -> str:
    """Map a work status onto Planned / In progress / Completed, deriving from
    the actual start/end dates when no explicit status is given."""
    low = str(raw).lower()
    if "progress" in low:
        return "In progress"
    if "complet" in low or "closed" in low or "cancel" in low:
        return "Completed"
    if "plan" in low or "propos" in low or "registered" in low or "advanced" in low:
        return "Planned"
    # Derive from actual dates when the status field is absent/unknown.
    has_start = bool(_field(rec, "actual_start_date_time", "actual_start_date",
                            "actualStartDate", default=""))
    has_end = bool(_field(rec, "actual_end_date_time", "actual_end_date",
                          "actualEndDate", default=""))
    if has_end:
        return "Completed"
    if has_start:
        return "In progress"
    return "Planned"


def _parse_date(value) -> date | None:
    if not value:
        return None
    value = str(value)
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", value)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", value)  # DD/MM/YYYY
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def _iso_date(value) -> str:
    d = _parse_date(value)
    return d.isoformat() if d else ""


def _fmt_date(value) -> str:
    """'2026-06-08' → 'Mon 8 June'. Blank if unparseable."""
    d = _parse_date(value)
    if not d:
        return ""
    return f"{d.strftime('%a')} {d.day} {d.strftime('%B')}"


def _date_range(start: str, end: str) -> str:
    """'Mon 8 June – Fri 12 June' (en dash); one side alone if only one date."""
    s, e = _fmt_date(start), _fmt_date(end)
    if s and e:
        return f"{s} – {e}"
    return s or e


def _summary(road, start, end, work_type, category, promoter, tm) -> str:
    """Plain-English sentence following the brief's template."""
    s, e = _fmt_date(start), _fmt_date(end)
    if s and e:
        when = f"from {s} to {e}"
    elif s:
        when = f"from {s}"
    elif e:
        when = f"until {e}"
    else:
        when = "on dates to be confirmed"

    wt_low = str(work_type).lower()
    verb = "will be closed" if "closure" in wt_low or "closed" in wt_low \
        else f"will see {work_type.lower()}"
    work_desc = f"{category.lower()} works" if category else "works"

    sentence = f"{road} {verb} {when} for {work_desc} by {promoter}."
    if tm:
        sentence += f" {tm}."
    return sentence
