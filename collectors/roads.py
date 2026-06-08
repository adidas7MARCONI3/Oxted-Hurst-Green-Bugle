"""Road closures and roadworks affecting Oxted & Hurst Green (RH8).

Two sources, primary → secondary, with graceful failure on either:

  1. Street Manager API (primary — official UK government street works
     database, no API key required)
     https://api.streetmanager.dft.gov.uk/experimental/activities
     Filtered to a 3 km radius of Oxted (lat 51.2567, long -0.0049).
     Returns planned roadworks, road closures and utility works. The
     experimental endpoint's shape varies, so parsing is tolerant of both
     bare lists and {activities|data|items} envelopes, and of snake_case
     or camelCase field names.

  2. Surrey County Council weekly highways bulletin (secondary — scrape)
     https://www.surreycc.gov.uk/roads-and-transport/roadworks-and-maintenance/roadworks/in-your-area
     Filtered to Tandridge / RH8 local terms.

Each item carries: road name, type of work, start date, end date, the
promoter (who is doing the works — Surrey CC, utility company, etc.) and a
working URL. Items are sorted current/soonest-first.
"""
import hashlib
import re
from datetime import date
from urllib.parse import quote_plus, urljoin
import httpx
from .base import BaseCollector, CollectionResult, Item, now_iso

STREET_MANAGER_API = "https://api.streetmanager.dft.gov.uk/experimental/activities"
SURREY_BULLETIN = (
    "https://www.surreycc.gov.uk/roads-and-transport/roadworks-and-maintenance/"
    "roadworks/in-your-area"
)

# Oxted town centre — Street Manager radius filter
AREA_LAT = 51.2567
AREA_LONG = -0.0049
AREA_RADIUS_M = 3000

# Local relevance terms for filtering the Surrey CC bulletin to our patch
LOCAL_TERMS = {"oxted", "hurst green", "tandridge", "limpsfield", "rh8"}

# A bulletin line names a specific road/place when it carries a road-type word
# or a classified-road number (A25, B2024…). Used to decide whether we can build
# a deep link to that exact road rather than the county-wide roadworks list.
ROAD_WORD_RE = re.compile(
    r"\b(road|lane|street|hill|way|close|avenue|crescent|drive|green|common|"
    r"bridge|level crossing|roundabout|junction|gardens|terrace|row|path|"
    r"footpath|bypass|highway)\b",
    re.IGNORECASE,
)
ROAD_CLASS_RE = re.compile(r"\b[AB]\d{2,4}\b")
# Anchor hrefs that point at an individual roadwork/closure rather than the
# generic landing page — the live-map providers Surrey CC links out to.
DEEP_LINK_HINTS = ("one.network", "roadworks.org", "elgin", "/works/", "permit")
SURREY_BASE = "https://www.surreycc.gov.uk"

# one.network is the live roadworks/closures map Surrey CC itself publishes to
# (and links individual works out to). When the bulletin doesn't hand us a
# per-closure link we point at one.network rather than the static council
# listing: its map search takes a free-text location, so we can centre it on a
# named road, or on Oxted for vague entries.
ONE_NETWORK = "https://one.network/"


def _one_network_search(place: str) -> str:
    """one.network live-map URL searched to a place (road or town)."""
    return f"{ONE_NETWORK}?search={quote_plus(place)}"


class RoadsCollector(BaseCollector):
    name = "roads"

    def collect(self) -> CollectionResult:
        seen: set[str] = set()
        items: list[Item] = []

        try:
            items.extend(self._fetch_street_manager(seen))
        except Exception as exc:
            print(f"[roads] Street Manager API failed: {exc}")

        try:
            items.extend(self._fetch_surrey_bulletin(seen))
        except Exception as exc:
            print(f"[roads] Surrey CC bulletin failed: {exc}")

        # Current/soonest-first: sort by start date ascending, blanks last.
        items.sort(key=lambda x: x.date or "9999-12-31")
        return CollectionResult(source=self.name, collected_at=now_iso(), items=items)

    # ── Street Manager (primary) ──────────────────────────────────────────
    def _fetch_street_manager(self, seen: set[str]) -> list[Item]:
        resp = httpx.get(
            STREET_MANAGER_API,
            params={
                "latitude": AREA_LAT,
                "longitude": AREA_LONG,
                "radius": AREA_RADIUS_M,
            },
            timeout=30,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        payload = resp.json()

        # Tolerate bare lists and common envelope shapes.
        if isinstance(payload, dict):
            records = (
                payload.get("activities")
                or payload.get("data")
                or payload.get("items")
                or payload.get("results")
                or []
            )
        else:
            records = payload
        if isinstance(records, dict):
            records = [records]

        items: list[Item] = []
        for rec in records:
            if not isinstance(rec, dict):
                continue

            def f(*keys, default=""):
                for k in keys:
                    if rec.get(k) not in (None, ""):
                        return rec[k]
                return default

            road = f("street_name", "streetName", "road_name", "roadName",
                     "location_description", "locationDescription",
                     default="Unknown road")
            work_type = f("activity_type", "activityType", "work_category",
                          "workCategory", "activity_name", "activityName",
                          default="Roadworks")
            promoter = f("promoter_organisation", "promoterOrganisation",
                         "highway_authority", "highwayAuthority",
                         "promoter", default="Highway authority")
            start = self._iso_date(
                f("start_date", "startDate", "actual_start_date_time",
                  "proposed_start_date", "proposedStartDate")
            )
            end = self._iso_date(
                f("end_date", "endDate", "actual_end_date_time",
                  "proposed_end_date", "proposedEndDate")
            )
            ref = f("work_reference_number", "workReferenceNumber",
                    "permit_reference_number", "activity_reference_number",
                    default=road)
            url = f("url", "link") or (
                "https://www.streetmanager.service.gov.uk/"
                f"works/{ref}" if ref and ref != road else SURREY_BULLETIN
            )

            uid = hashlib.md5(f"sm{ref}{road}{start}".encode()).hexdigest()[:12]
            if uid in seen:
                continue
            seen.add(uid)

            when = self._when_phrase(start, end)
            items.append(Item(
                id=uid,
                title=f"{work_type} — {road}",
                description=(
                    f"{work_type} on {road}{when}. "
                    f"Works carried out by {promoter}. Source: Street Manager."
                ),
                date=start,
                category="roadworks",
                url=url,
                data={
                    "road": road,
                    "work_type": work_type,
                    "promoter": promoter,
                    "start_date": start,
                    "end_date": end,
                    "source": "Street Manager",
                },
            ))
        return items

    # ── Surrey CC weekly bulletin (secondary) ─────────────────────────────
    def _fetch_surrey_bulletin(self, seen: set[str]) -> list[Item]:
        resp = httpx.get(
            SURREY_BULLETIN,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (OxtedBugle roads collector)"},
        )
        resp.raise_for_status()
        html = resp.text

        # Capture any per-closure deep links the bulletin itself provides
        # (Surrey CC links individual works out to live-map providers) before
        # we flatten the markup — that's where the specific URLs live.
        deep_links = self._collect_roadwork_links(html)

        # Strip tags to plain text and split into candidate lines; the bulletin
        # is rendered as a list of road entries. We keep only lines that mention
        # one of our local terms so the feed stays relevant to RH8.
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html,
                      flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "\n", text)
        text = re.sub(r"&nbsp;|&amp;", " ", text)
        lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]

        items: list[Item] = []
        for line in lines:
            if len(line) < 12:
                continue
            low = line.lower()
            if not any(term in low for term in LOCAL_TERMS):
                continue

            uid = hashlib.md5(f"surrey{line}".encode()).hexdigest()[:12]
            if uid in seen:
                continue
            seen.add(uid)

            # Deep link to the specific closure rather than the county-wide list:
            # prefer a link the bulletin gave us, otherwise point at the exact
            # road. Vague prose entries keep the generic bulletin page.
            url = self._deep_link_for(line, deep_links)

            items.append(Item(
                id=uid,
                title=f"Surrey CC roadworks — {line[:80]}",
                description=(
                    f"{line} Listed in the Surrey County Council weekly "
                    f"highways bulletin for the Tandridge area."
                ),
                date="",
                category="roadworks",
                url=url,
                data={
                    "road": line[:120],
                    "work_type": "Roadworks",
                    "promoter": "Surrey County Council",
                    "start_date": "",
                    "end_date": "",
                    "source": "Surrey CC bulletin",
                },
            ))
        return items

    # ── deep linking ──────────────────────────────────────────────────────
    @staticmethod
    def _collect_roadwork_links(html: str) -> list[tuple[str, str]]:
        """Extract (anchor_text, absolute_href) pairs that look like links to an
        individual roadwork/closure, so a bulletin entry can be matched to its
        own page instead of the generic listing."""
        links: list[tuple[str, str]] = []
        for m in re.finditer(
            r'<a\b[^>]*\bhref="([^"]+)"[^>]*>(.*?)</a>',
            html, flags=re.DOTALL | re.IGNORECASE,
        ):
            href = m.group(1).strip()
            atext = re.sub(r"<[^>]+>", " ", m.group(2))
            atext = re.sub(r"&nbsp;|&amp;", " ", atext)
            atext = re.sub(r"\s+", " ", atext).strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            low = href.lower()
            # Only links that resolve to a *specific* work, not the landing page.
            if not any(hint in low for hint in DEEP_LINK_HINTS):
                continue
            links.append((atext, urljoin(SURREY_BASE + "/", href)))
        return links

    @classmethod
    def _deep_link_for(cls, line: str, deep_links: list[tuple[str, str]]) -> str:
        """Best available URL for a bulletin entry, most specific first."""
        low = line.lower()
        # 1) A link from the page whose text appears in (or contains) this entry.
        best = ""
        best_len = 0
        for atext, href in deep_links:
            a = atext.lower()
            if len(a) >= 6 and (a in low or low in a) and len(a) > best_len:
                best, best_len = href, len(a)
        if best:
            return best
        # 2) Otherwise search one.network's live map for the exact road, if we
        #    can name one — that's the closures map, not just the road geometry.
        road = cls._clean_road_name(line)
        if road and (ROAD_WORD_RE.search(road) or ROAD_CLASS_RE.search(road)):
            return _one_network_search(f"{road}, Surrey")
        # 3) Vague prose ("upcoming works across Tandridge") → one.network for
        #    the wider Oxted area, rather than the static council listing.
        return _one_network_search("Oxted, Surrey")

    @staticmethod
    def _clean_road_name(line: str) -> str:
        """Trim a bulletin line down to the road/place it names: drop any work
        description after a dash and any trailing punctuation."""
        road = re.split(r"\s[—–-]\s", line)[0]
        road = re.sub(r"\b(roadworks?|road works|closure|closed)\b.*$", "", road,
                      flags=re.IGNORECASE)
        return road.strip(" .,:;").strip()

    # ── helpers ───────────────────────────────────────────────────────────
    @staticmethod
    def _iso_date(value: str) -> str:
        """Normalise a date/datetime string to YYYY-MM-DD; blank if unparseable."""
        if not value:
            return ""
        value = str(value)
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", value)
        if m:
            return m.group(0)
        # DD/MM/YYYY
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", value)
        if m:
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        return ""

    @staticmethod
    def _when_phrase(start: str, end: str) -> str:
        if start and end:
            return f" from {start} to {end}"
        if start:
            return f" starting {start}"
        if end:
            return f" until {end}"
        return ""
