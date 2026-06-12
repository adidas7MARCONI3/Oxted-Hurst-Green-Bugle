"""Road closures and roadworks affecting Oxted & Hurst Green (RH8).

Source: the DfT **Street Manager Open Data** permit register — the free, public,
**keyless** archive of UK street and road works published by the Department for
Transport. (We deliberately use the open-data feed rather than the live
Street Manager API v3, which requires a registered-organisation API key.)

    Open Data: https://opendata.streetmanager.service.gov.uk/permit/latest.json
    Auth:      none — public open data, no API key
    Docs:      https://department-for-transport-streetmanager.github.io/
               street-manager-docs/open-data/

The open-data feed is national, so we filter to Oxted client-side: by a 3 km
haversine radius of the town centre (lat 51.2567, long -0.0049) when a record
carries WGS84 coordinates, otherwise by an area-name keyword match (Oxted /
Hurst Green / Limpsfield / RH8). Records we can't place locally are dropped.

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
     major works by Thames Water. Full road closure with diversion."

Items are sorted current/soonest-first.
"""
import hashlib
import json
import math
import os
import re
from datetime import date
import httpx
from .base import BaseCollector, CollectionResult, Item, now_iso

# Free, keyless Street Manager Open Data permit feed. Overridable via env for
# pinning to a specific dated archive file if the "latest" path ever moves.
OPEN_DATA_URL = os.getenv(
    "STREET_MANAGER_OPEN_DATA_URL",
    "https://opendata.streetmanager.service.gov.uk/permit/latest.json",
)

# Oxted town centre — 3 km radius filter (used when a record carries WGS84
# coordinates; the open-data location is otherwise British National Grid).
AREA_LAT = 51.2567
AREA_LONG = -0.0049
AREA_RADIUS_M = 3000

# Fallback area filter when a record has no usable WGS84 coordinates: keep works
# whose street/area/town text mentions one of these (case-insensitive).
AREA_KEYWORDS = ("oxted", "hurst green", "limpsfield", "rh8")

# Deep-link templates required by the brief.
ONE_NETWORK_USRN = "https://one.network/?USRN={usrn}"
STREET_MANAGER_PUBLIC = "https://streetmanager.dft.gov.uk/works/{ref}"


class RoadsCollector(BaseCollector):
    name = "roads"

    def __init__(self):
        self.open_data_url = OPEN_DATA_URL

    def collect(self) -> CollectionResult:
        items: list[Item] = []
        try:
            items = self._fetch_works()
        except Exception as exc:
            print(f"[roads] Street Manager Open Data fetch failed: {exc}")

        # Current/soonest-first: by start date ascending, blanks last.
        items.sort(key=lambda x: x.date or "9999-12-31")
        return CollectionResult(source=self.name, collected_at=now_iso(), items=items)

    # ── Street Manager Open Data ──────────────────────────────────────────
    def _fetch_works(self) -> list[Item]:
        resp = httpx.get(
            self.open_data_url,
            headers={"Accept": "application/json"},
            timeout=60,
            follow_redirects=True,
        )
        # Make failures visible in the daily run's logs: a 404/403 or an empty
        # body here is the usual reason the roads section shows nothing.
        status = getattr(resp, "status_code", "?")
        print(f"[roads] GET {self.open_data_url} -> HTTP {status}")
        if isinstance(status, int) and status >= 400:
            snippet = (resp.text or "")[:300].replace("\n", " ")
            print(f"[roads] open-data feed returned HTTP {status}: {snippet}")
        resp.raise_for_status()
        records = _load_records(resp)
        print(f"[roads] parsed {len(records)} raw record(s) from the open-data feed")

        items: list[Item] = []
        seen: set[str] = set()
        for raw in records:
            if not isinstance(raw, dict):
                continue
            # Open-data event records wrap the permit under `object_data`.
            rec = raw.get("object_data") if isinstance(raw.get("object_data"), dict) else raw
            if not _within_area(rec):
                continue

            road = _field(rec, "street_name", "streetName", "road_name",
                          "roadName", "location_description",
                          "locationDescription", "area_name",
                          default="Unknown road")
            work_type = _field(rec, "activity_type", "activityType", "work_type",
                               "workType", "works_type", "permit_status",
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
                             "permit_reference_number", "permitReferenceNumber",
                             default="")).strip()
            start = _iso_date(_field(rec, "proposed_start_date", "proposedStartDate",
                                     "start_date", "startDate",
                                     "actual_start_date", "actual_start_date_time"))
            end = _iso_date(_field(rec, "proposed_end_date", "proposedEndDate",
                                   "end_date", "endDate",
                                   "actual_end_date", "actual_end_date_time"))
            status = _normalise_status(
                _field(rec, "permit_status", "permitStatus", "work_status",
                       "workStatus", "status", default=""),
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
                    "source": "Street Manager Open Data",
                },
            ))
        print(f"[roads] {len(items)} work(s) within the Oxted area after filtering")
        return items


# ── helpers ───────────────────────────────────────────────────────────────
def _load_records(resp) -> list:
    """Read the works out of a JSON array, an envelope, or NDJSON (one JSON
    object per line — a common open-data publication shape)."""
    try:
        return _records(resp.json())
    except (ValueError, json.JSONDecodeError):
        pass
    out: list = []
    for line in resp.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except (ValueError, json.JSONDecodeError):
            continue
    return out


def _records(payload) -> list:
    """Pull the list of works out of a bare list or a common envelope shape."""
    if isinstance(payload, dict):
        records = (payload.get("works") or payload.get("data")
                   or payload.get("items") or payload.get("results")
                   or payload.get("permits") or [])
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


def _within_area(rec: dict) -> bool:
    """Keep records that are local to Oxted. The open-data feed is national and
    has no server-side radius, so this filters client-side: a 3 km haversine
    when WGS84 coordinates are present, otherwise an area-name keyword match.
    Records we can't place locally are dropped."""
    lat = _coerce_float(_field(rec, "latitude", "lat", default=None))
    lng = _coerce_float(_field(rec, "longitude", "long", "lng", default=None))
    if lat is not None and lng is not None:
        return _haversine_m(AREA_LAT, AREA_LONG, lat, lng) <= AREA_RADIUS_M

    haystack = " ".join(str(_field(rec, k, default="")) for k in (
        "street_name", "streetName", "area_name", "areaName",
        "town", "location_description", "locationDescription",
    )).lower()
    return any(kw in haystack for kw in AREA_KEYWORDS)


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
    """Map a permit/work status onto Planned / In progress / Completed, deriving
    from the actual start/end dates when no explicit status is given."""
    low = str(raw).lower()
    if "progress" in low or "started" in low:
        return "In progress"
    if "complet" in low or "closed" in low or "cancel" in low \
            or "revoked" in low or "refus" in low:
        return "Completed"
    if ("plan" in low or "propos" in low or "registered" in low
            or "advanced" in low or "grant" in low or "submit" in low):
        return "Planned"
    # Derive from actual dates when the status field is absent/unknown.
    has_start = bool(_field(rec, "actual_start_date", "actual_start_date_time",
                            "actualStartDate", default=""))
    has_end = bool(_field(rec, "actual_end_date", "actual_end_date_time",
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
