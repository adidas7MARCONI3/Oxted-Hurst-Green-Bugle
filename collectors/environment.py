"""Environment Agency: flood warnings, air quality for RH8 area."""
import hashlib
import httpx
from .base import BaseCollector, CollectionResult, Item, now_iso

# Bounding box covering Oxted/Hurst Green area (approx)
AREA_BBOX = "-0.10,51.22,0.05,51.30"
FLOOD_API = "https://environment.data.gov.uk/flood-monitoring/id/floods"
AQ_API = "https://api.erg.ic.ac.uk/AirQuality/Hourly/MonitoringIndex/GroupName=Surrey/Json"


class EnvironmentCollector(BaseCollector):
    name = "environment"

    def collect(self) -> CollectionResult:
        items: list[Item] = []
        items.extend(self._fetch_floods())
        items.extend(self._fetch_air_quality())
        items.sort(key=lambda x: x.date, reverse=True)
        return CollectionResult(source=self.name, collected_at=now_iso(), items=items)

    def _fetch_floods(self) -> list[Item]:
        try:
            resp = httpx.get(
                FLOOD_API,
                params={"lat": 51.2572, "long": -0.0043, "dist": 10},
                timeout=20,
            )
            resp.raise_for_status()
            warnings = resp.json().get("items", [])
        except Exception as exc:
            print(f"[environment] flood API failed: {exc}")
            return []

        items = []
        severity_labels = {1: "Severe Flood Warning", 2: "Flood Warning",
                          3: "Flood Alert", 4: "Warning No Longer In Force"}
        for w in warnings:
            severity = w.get("severity", 4)
            area = w.get("floodArea", {}).get("label", "Unknown area")
            description = w.get("description", area)
            uid = hashlib.md5(w.get("@id", description).encode()).hexdigest()[:12]
            raised = w.get("timeRaised", now_iso())[:10]
            items.append(Item(
                id=uid,
                title=f"{severity_labels.get(severity, 'Flood Notice')} — {area}",
                description=description[:400],
                date=raised,
                category="flood",
                url=w.get("floodArea", {}).get("riverOrSea", ""),
                data={"severity": severity, "raw": w},
            ))
        return items

    def _fetch_air_quality(self) -> list[Item]:
        try:
            resp = httpx.get(AQ_API, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            print(f"[environment] air quality API failed: {exc}")
            return []

        items = []
        sites = data.get("HourlyAirQualityIndex", {}).get("LocalAuthority", [])
        if isinstance(sites, dict):
            sites = [sites]

        for la in sites:
            if "Tandridge" not in la.get("@LocalAuthorityName", ""):
                continue
            species_list = la.get("Site", [])
            if isinstance(species_list, dict):
                species_list = [species_list]
            for site in species_list:
                name = site.get("@SiteName", "Unknown")
                species = site.get("Species", [])
                if isinstance(species, dict):
                    species = [species]
                for sp in species:
                    index = int(sp.get("@AirQualityIndex", 0))
                    band = sp.get("@AirQualityBand", "Unknown")
                    pollutant = sp.get("@SpeciesCode", "")
                    if index <= 3:
                        continue  # only report moderate+
                    uid = hashlib.md5(f"{name}{pollutant}".encode()).hexdigest()[:12]
                    items.append(Item(
                        id=uid,
                        title=f"Air Quality {band} — {name} ({pollutant})",
                        description=f"{pollutant} at {name}: index {index} ({band}). "
                                    f"Index above 3 may affect sensitive groups.",
                        date=now_iso()[:10],
                        category="air_quality",
                        url="https://uk-air.defra.gov.uk/",
                        data={"index": index, "band": band, "pollutant": pollutant},
                    ))
        return items
