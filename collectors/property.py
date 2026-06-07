"""Recent property sales from Land Registry Price Paid Data via SPARQL."""
import hashlib
import httpx
from .base import BaseCollector, CollectionResult, Item, now_iso

SPARQL_ENDPOINT = "https://landregistry.data.gov.uk/landregistry/query"

QUERY = """
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX lrppi: <http://landregistry.data.gov.uk/def/ppi/>
PREFIX lrcommon: <http://landregistry.data.gov.uk/def/common/>

SELECT ?paon ?saon ?street ?town ?postcode ?amount ?date ?category
WHERE {{
  ?trans a lrppi:TransactionRecord ;
         lrppi:pricePaid ?amount ;
         lrppi:transactionDate ?date ;
         lrppi:propertyType ?category ;
         lrppi:propertyAddress ?addr .
  ?addr lrcommon:postcode ?postcode .
  OPTIONAL {{ ?addr lrcommon:paon ?paon }}
  OPTIONAL {{ ?addr lrcommon:saon ?saon }}
  OPTIONAL {{ ?addr lrcommon:street ?street }}
  OPTIONAL {{ ?addr lrcommon:town ?town }}
  FILTER (STRSTARTS(?postcode, "RH8"))
  FILTER (?date >= "{cutoff}"^^xsd:date)
}}
ORDER BY DESC(?date)
LIMIT 25
"""


class PropertyCollector(BaseCollector):
    name = "property"

    def collect(self) -> CollectionResult:
        from datetime import date, timedelta
        cutoff = (date.today() - timedelta(days=90)).isoformat()
        items = []
        try:
            resp = httpx.post(
                SPARQL_ENDPOINT,
                data={"query": QUERY.format(cutoff=cutoff), "output": "json"},
                timeout=30,
            )
            resp.raise_for_status()
            bindings = resp.json()["results"]["bindings"]
        except Exception as exc:
            print(f"[property] SPARQL failed: {exc}")
            bindings = []

        for b in bindings:
            def v(k):
                return b.get(k, {}).get("value", "")
            paon = v("paon"); saon = v("saon"); street = v("street")
            address_parts = [p for p in [saon, paon, street] if p]
            address = " ".join(address_parts) or "Unknown address"
            amount = int(float(v("amount"))) if v("amount") else 0
            cat_raw = v("category").split("/")[-1] if v("category") else "unknown"
            cat = {"detached": "Detached", "semi-detached": "Semi-detached",
                   "terraced": "Terraced", "flat-maisonette": "Flat"}.get(cat_raw, cat_raw.title())
            uid = hashlib.md5(f"{address}{v('date')}{amount}".encode()).hexdigest()[:12]
            items.append(Item(
                id=uid,
                title=f"{cat}, {address.title()} — £{amount:,}",
                description=f"A {cat.lower()} property at {address.title()}, {v('postcode')} "
                            f"sold for £{amount:,} on {v('date')}.",
                date=v("date") or now_iso()[:10],
                category="property",
                url="https://landregistry.data.gov.uk/app/ppd",
                data={"amount": amount, "category": cat, "postcode": v("postcode")},
            ))

        return CollectionResult(source=self.name, collected_at=now_iso(), items=items)
