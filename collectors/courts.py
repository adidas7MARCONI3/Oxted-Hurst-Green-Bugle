"""Court judgements from the National Archives Find Case Law (Atom feed)
and planning appeal decisions from the Planning Inspectorate ACP portal.

No API keys required.

Sources:
  1. https://caselaw.nationalarchives.gov.uk/atom.xml — public Atom feed,
     searched for "Oxted", "Hurst Green", and "Tandridge".
     Relevance filter: local term must appear in the case title.
     Deduplication across all three queries by judgement URL.

  2. https://acp.planninginspectorate.gov.uk/ViewAPI/Appeals — Planning
     Inspectorate ACP REST API for Tandridge (LPA code TAN).
     Falls back gracefully if the portal is unreachable.
"""
import hashlib
import httpx
from xml.etree import ElementTree as ET
from .base import BaseCollector, CollectionResult, Item, now_iso

CASELAW_ATOM = "https://caselaw.nationalarchives.gov.uk/atom.xml"
PINS_API = "https://acp.planninginspectorate.gov.uk/ViewAPI/Appeals"
PINS_LPA_CODE = "TAN"

NS_ATOM = "{http://www.w3.org/2005/Atom}"
NS_TNA = "{https://caselaw.nationalarchives.gov.uk}"

SEARCH_QUERIES = ["Oxted", "Hurst Green", "Tandridge"]
LOCAL_TERMS = {"oxted", "hurst green", "tandridge"}


class CourtsCollector(BaseCollector):
    name = "courts"

    def collect(self) -> CollectionResult:
        seen_urls: set[str] = set()
        items: list[Item] = []

        for query in SEARCH_QUERIES:
            try:
                items.extend(self._fetch_caselaw(query, seen_urls))
            except Exception as exc:
                print(f"[courts] caselaw '{query}' failed: {exc}")

        try:
            items.extend(self._fetch_pins(seen_urls))
        except Exception as exc:
            print(f"[courts] Planning Inspectorate unavailable: {exc}")

        items.sort(key=lambda x: x.date, reverse=True)
        return CollectionResult(source=self.name, collected_at=now_iso(), items=items[:30])

    def _fetch_caselaw(self, query: str, seen_urls: set[str]) -> list[Item]:
        resp = httpx.get(
            CASELAW_ATOM,
            params={"query": query, "page": 1},
            timeout=20,
            follow_redirects=True,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        items = []
        for entry in root.findall(f"{NS_ATOM}entry"):
            link_el = entry.find(f"{NS_ATOM}link[@rel='alternate']")
            url = link_el.get("href", "") if link_el is not None else ""
            if not url or url in seen_urls:
                continue

            title = entry.findtext(f"{NS_ATOM}title", "").strip()
            published = (entry.findtext(f"{NS_ATOM}published", "") or "")[:10]
            court = entry.findtext(f"{NS_ATOM}author/{NS_ATOM}name", "")

            # Neutral citation — first tna:identifier that starts with "["
            citation = ""
            for ident in entry.findall(f"{NS_TNA}identifier"):
                text = ident.text or ""
                if text.startswith("["):
                    citation = text
                    break

            # Only include cases where a local term appears in the case title.
            # Cases where the term only appears in the body text are too loosely connected.
            if not any(term in title.lower() for term in LOCAL_TERMS):
                continue

            seen_urls.add(url)
            uid = hashlib.md5(url.encode()).hexdigest()[:12]
            full_title = f"{title} {citation}".strip()
            description = (
                f"{court} judgement concerning the {query} area. "
                f"Citation: {citation}. Full text available at the link."
                if citation else
                f"{court} judgement concerning the {query} area. Full text available at the link."
            )

            items.append(Item(
                id=uid,
                title=full_title,
                description=description,
                date=published or now_iso()[:10],
                category="courts",
                url=url,
                data={
                    "court": court,
                    "citation": citation,
                    "query": query,
                    "source": "national_archives",
                },
            ))

        return items

    def _fetch_pins(self, seen_urls: set[str]) -> list[Item]:
        resp = httpx.get(
            PINS_API,
            params={"LPACode": PINS_LPA_CODE, "PageSize": 20, "PageNumber": 1},
            timeout=10,
            follow_redirects=True,
        )
        resp.raise_for_status()
        data = resp.json()

        appeals = data if isinstance(data, list) else data.get("appeals", data.get("results", []))
        items = []
        for appeal in appeals:
            ref = appeal.get("CaseReference") or appeal.get("caseReference") or ""
            url = (
                appeal.get("CaseURL") or appeal.get("caseURL")
                or (f"https://acp.planninginspectorate.gov.uk/ViewCase?CaseRef={ref}" if ref else "")
            )
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            address = appeal.get("SiteAddress") or appeal.get("siteAddress") or "Unknown address"
            decision = appeal.get("Decision") or appeal.get("decision") or ""
            appeal_type = appeal.get("AppealType") or appeal.get("appealType") or "Planning appeal"
            date_raw = appeal.get("DecisionDate") or appeal.get("decisionDate") or now_iso()
            date_str = date_raw[:10]

            uid = hashlib.md5((ref or url).encode()).hexdigest()[:12]
            items.append(Item(
                id=uid,
                title=f"Planning appeal: {address[:80]}" + (f" [{decision}]" if decision else ""),
                description=(
                    f"{appeal_type} for {address}. "
                    f"Decision: {decision or 'pending'}. Reference: {ref}."
                ),
                date=date_str,
                category="planning_appeal",
                url=url,
                data={
                    "reference": ref,
                    "decision": decision,
                    "type": appeal_type,
                    "source": "pins",
                },
            ))

        return items
