"""Live train data via Darwin OpenLDBWS SOAP API.

Register for a free API key at:
https://realtime.nationalrail.co.uk/OpenLDBWSRegistration/

Set DARWIN_API_KEY in .env.
"""
import os
import hashlib
import httpx
from xml.etree import ElementTree as ET
from .base import BaseCollector, CollectionResult, Item, now_iso

DARWIN_ENDPOINT = "https://lite.realtime.nationalrail.co.uk/OpenLDBWS/ldb11.asmx"
DARWIN_NS = "http://thalesgroup.com/RTTI/2021-11-01/ldb/"
TOKEN_NS = "http://thalesgroup.com/RTTI/2013-11-28/Token/types"

STATIONS = [
    ("OXT", "Oxted"),
    ("HGS", "Hurst Green"),
]

SOAP_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
               xmlns:typ="{token_ns}">
  <soap:Header>
    <typ:AccessToken>
      <typ:TokenValue>{token}</typ:TokenValue>
    </typ:AccessToken>
  </soap:Header>
  <soap:Body>
    <GetDepartureBoardRequest xmlns="{ns}">
      <numRows>10</numRows>
      <crs>{crs}</crs>
    </GetDepartureBoardRequest>
  </soap:Body>
</soap:Envelope>"""


def _text(el, tag: str, ns: str = DARWIN_NS) -> str:
    found = el.find(f"{{{ns}}}{tag}")
    return found.text if found is not None and found.text else ""


class TrainsCollector(BaseCollector):
    name = "trains"

    def __init__(self):
        self.api_key = os.getenv("DARWIN_API_KEY", "")

    def collect(self) -> CollectionResult:
        items: list[Item] = []
        if not self.api_key:
            print("[trains] DARWIN_API_KEY not set — skipping live data")
            return CollectionResult(source=self.name, collected_at=now_iso(), items=[])

        for crs, station_name in STATIONS:
            try:
                items.extend(self._fetch_station(crs, station_name))
            except Exception as exc:
                print(f"[trains] {station_name} failed: {exc}")

        return CollectionResult(source=self.name, collected_at=now_iso(), items=items)

    def _fetch_station(self, crs: str, station_name: str) -> list[Item]:
        body = SOAP_TEMPLATE.format(
            token_ns=TOKEN_NS, ns=DARWIN_NS, token=self.api_key, crs=crs
        )
        resp = httpx.post(
            DARWIN_ENDPOINT,
            content=body.encode(),
            headers={"Content-Type": "text/xml; charset=utf-8",
                     "SOAPAction": "http://thalesgroup.com/RTTI/2021-11-01/ldb/GetDepartureBoard"},
            timeout=15,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        body_el = root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Body")
        board = body_el.find(f".//{{{DARWIN_NS}}}GetStationBoardResult") if body_el else None
        if board is None:
            return []

        services_el = board.find(f"{{{DARWIN_NS}}}trainServices")
        if services_el is None:
            return []

        items = []
        for svc in services_el:
            scheduled = _text(svc, "std")
            estimated = _text(svc, "etd")
            platform = _text(svc, "platform")
            operator = _text(svc, "operator")
            destination = ""
            dest_el = svc.find(f"{{{DARWIN_NS}}}destination")
            if dest_el is not None:
                loc = dest_el.find(f"{{{DARWIN_NS}}}location")
                if loc is not None:
                    destination = _text(loc, "locationName")

            is_disrupted = estimated not in ("On time", scheduled, "") and estimated != "Delayed"
            is_cancelled = _text(svc, "isCancelled") == "true"

            status = "Cancelled" if is_cancelled else estimated or "On time"
            uid = hashlib.md5(f"{crs}{scheduled}{destination}".encode()).hexdigest()[:12]

            items.append(Item(
                id=uid,
                title=f"{station_name} → {destination}: {scheduled} [{status}]",
                description=(
                    f"{operator} service from {station_name} to {destination}, "
                    f"scheduled {scheduled}. Status: {status}."
                    + (f" Platform {platform}." if platform else "")
                ),
                date=now_iso()[:10],
                category="trains",
                url="https://www.nationalrail.co.uk/",
                data={
                    "station": station_name, "crs": crs, "scheduled": scheduled,
                    "estimated": estimated, "destination": destination,
                    "operator": operator, "platform": platform,
                    "cancelled": is_cancelled, "disrupted": is_disrupted,
                },
            ))
        return items

    def has_disruptions(self) -> bool:
        result = self.collect()
        return any(
            i.data.get("cancelled") or i.data.get("disrupted")
            for i in result.items
        )
