"""Basic unit tests for collectors — no network calls, no API keys."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from collectors.base import Item, CollectionResult, now_iso


# ── CollectionResult I/O ──────────────────────────────────────────────────

def make_result(source="test", n=3):
    return CollectionResult(
        source=source,
        collected_at=now_iso(),
        items=[
            Item(id=str(i), title=f"Item {i}", description="desc",
                 date="2026-06-07", category="test")
            for i in range(n)
        ],
    )


def test_collection_result_save_load(tmp_path):
    result = make_result("crime", 5)
    result.save(str(tmp_path))
    loaded = CollectionResult.load("crime", str(tmp_path))
    assert loaded.source == "crime"
    assert len(loaded.items) == 5
    assert loaded.items[0].title == "Item 0"


def test_collection_result_json_structure(tmp_path):
    result = make_result("planning", 2)
    path = result.save(str(tmp_path))
    raw = json.loads(path.read_text())
    assert "source" in raw
    assert "collected_at" in raw
    assert "items" in raw
    assert raw["items"][0]["id"] == "0"


# ── Crime collector (mocked) ──────────────────────────────────────────────

def test_crime_collector_parses_response():
    from collectors.crime import CrimeCollector
    mock_crimes = [
        {"id": 1, "category": "anti-social-behaviour",
         "location": {"street": {"name": "High Street"}},
         "outcome_status": {"category": "Under investigation"},
         "month": "2026-05"},
        {"id": 2, "category": "theft",
         "location": {"street": {"name": "Station Road"}},
         "outcome_status": None,
         "month": "2026-05"},
    ]
    with patch("collectors.crime.httpx.get") as mock_get:
        mock_get.return_value.json.return_value = mock_crimes
        mock_get.return_value.raise_for_status = MagicMock()
        result = CrimeCollector().collect()

    assert result.source == "crime"
    assert len(result.items) == 2
    assert "High Street" in result.items[0].title or "Anti" in result.items[0].title


def test_crime_collector_handles_network_error():
    from collectors.crime import CrimeCollector
    import httpx
    with patch("collectors.crime.httpx.get", side_effect=httpx.ConnectError("refused")):
        result = CrimeCollector().collect()
    assert result.source == "crime"
    assert result.items == []


# ── Events admin ──────────────────────────────────────────────────────────

def test_events_loads_approved_submissions(tmp_path):
    approved = tmp_path / "approved"
    approved.mkdir()
    event = {"id": "abc123", "title": "Summer Fete", "date": "2026-07-04",
              "description": "Annual summer fete at the village hall.", "url": ""}
    (approved / "abc123.json").write_text(json.dumps(event))

    from collectors.events import EventsCollector, SUBMISSIONS_DIR
    collector = EventsCollector()

    with patch("collectors.events.SUBMISSIONS_DIR", approved):
        result = collector._load_approved_submissions()

    assert len(result) == 1
    assert result[0].title == "Summer Fete"


# ── Property SPARQL ──────────────────────────────────────────────────────

def test_property_collector_parses_sparql():
    from collectors.property import PropertyCollector
    mock_response = {
        "results": {
            "bindings": [{
                "paon": {"value": "14"},
                "street": {"value": "Station Road East"},
                "postcode": {"value": "RH8 0PG"},
                "amount": {"value": "485000"},
                "date": {"value": "2026-05-15"},
                "category": {"value": "http://landregistry.data.gov.uk/def/common/detached"},
            }]
        }
    }
    with patch("collectors.property.httpx.post") as mock_post:
        mock_post.return_value.json.return_value = mock_response
        mock_post.return_value.raise_for_status = MagicMock()
        result = PropertyCollector().collect()

    assert len(result.items) == 1
    assert "485,000" in result.items[0].title
    assert result.items[0].data["postcode"] == "RH8 0PG"


# ── Trains collector (Darwin OpenLDBWS) ───────────────────────────────────

# A realistic Darwin reply whose StationBoard children span MULTIPLE versioned
# `.../ldb/types` namespaces (2015-11-27 and 2017-10-01) — exactly the shape
# that broke single-namespace parsing and produced empty boards.
DARWIN_MULTI_NS_RESPONSE = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GetDepartureBoardResponse xmlns="http://thalesgroup.com/RTTI/2021-11-01/ldb/">
      <GetStationBoardResult xmlns="http://thalesgroup.com/RTTI/2017-10-01/ldb/types">
        <lt:locationName xmlns:lt="http://thalesgroup.com/RTTI/2015-11-27/ldb/types">Oxted</lt:locationName>
        <lt:crs xmlns:lt="http://thalesgroup.com/RTTI/2015-11-27/ldb/types">OXT</lt:crs>
        <lt7:trainServices xmlns:lt7="http://thalesgroup.com/RTTI/2017-10-01/ldb/types">
          <lt7:service>
            <lt4:std xmlns:lt4="http://thalesgroup.com/RTTI/2015-11-27/ldb/types">09:15</lt4:std>
            <lt4:etd xmlns:lt4="http://thalesgroup.com/RTTI/2015-11-27/ldb/types">On time</lt4:etd>
            <lt4:platform xmlns:lt4="http://thalesgroup.com/RTTI/2015-11-27/ldb/types">2</lt4:platform>
            <lt4:operator xmlns:lt4="http://thalesgroup.com/RTTI/2015-11-27/ldb/types">Southern</lt4:operator>
            <lt5:destination xmlns:lt5="http://thalesgroup.com/RTTI/2017-10-01/ldb/types">
              <lt4:location xmlns:lt4="http://thalesgroup.com/RTTI/2015-11-27/ldb/types">
                <lt4:locationName>London Bridge</lt4:locationName>
                <lt4:crs>LBG</lt4:crs>
              </lt4:location>
            </lt5:destination>
          </lt7:service>
          <lt7:service>
            <lt4:std xmlns:lt4="http://thalesgroup.com/RTTI/2015-11-27/ldb/types">09:30</lt4:std>
            <lt4:etd xmlns:lt4="http://thalesgroup.com/RTTI/2015-11-27/ldb/types">Cancelled</lt4:etd>
            <lt4:isCancelled xmlns:lt4="http://thalesgroup.com/RTTI/2015-11-27/ldb/types">true</lt4:isCancelled>
            <lt4:operator xmlns:lt4="http://thalesgroup.com/RTTI/2015-11-27/ldb/types">Southern</lt4:operator>
            <lt5:destination xmlns:lt5="http://thalesgroup.com/RTTI/2017-10-01/ldb/types">
              <lt4:location xmlns:lt4="http://thalesgroup.com/RTTI/2015-11-27/ldb/types">
                <lt4:locationName>East Grinstead</lt4:locationName>
                <lt4:crs>EGR</lt4:crs>
              </lt4:location>
            </lt5:destination>
          </lt7:service>
        </lt7:trainServices>
      </GetStationBoardResult>
    </GetDepartureBoardResponse>
  </soap:Body>
</soap:Envelope>"""


def test_trains_collector_parses_multi_namespace_response():
    from collectors.trains import TrainsCollector
    collector = TrainsCollector()
    collector.api_key = "test-key"  # bypass the no-key skip

    resp = MagicMock()
    resp.content = DARWIN_MULTI_NS_RESPONSE.encode()
    resp.raise_for_status = MagicMock()
    with patch("collectors.trains.httpx.post", return_value=resp):
        result = collector.collect()

    assert result.source == "trains"
    # Two stations are queried with the same mocked reply → 2 services each.
    assert len(result.items) == 4

    first = result.items[0]
    assert first.data["destination"] == "London Bridge"
    assert first.data["scheduled"] == "09:15"
    assert first.data["operator"] == "Southern"
    assert first.data["platform"] == "2"
    assert first.data["cancelled"] is False

    cancelled = [i for i in result.items if i.data["cancelled"]]
    assert len(cancelled) == 2  # one per station
    assert cancelled[0].data["destination"] == "East Grinstead"
    assert "Cancelled" in cancelled[0].title


def test_trains_request_namespace_matches_endpoint_version():
    """ldb11.asmx is version-locked to the 2017-10-01 schema. Sending a
    mismatched namespace/SOAPAction makes OpenLDBWS return HTTP 500 (the bug
    that left the board empty). Assert the outgoing request stays in sync."""
    import collectors.trains as trains
    from collectors.trains import TrainsCollector
    collector = TrainsCollector()
    collector.api_key = "test-key"

    resp = MagicMock()
    resp.content = DARWIN_MULTI_NS_RESPONSE.encode()
    resp.raise_for_status = MagicMock()
    with patch("collectors.trains.httpx.post", return_value=resp) as mock_post:
        collector.collect()

    # ldb11.asmx ⇒ 2017-10-01 schema, both in body and SOAPAction header.
    assert "ldb11.asmx" in trains.DARWIN_ENDPOINT
    assert trains.DARWIN_NS == "http://thalesgroup.com/RTTI/2017-10-01/ldb/"

    _, kwargs = mock_post.call_args
    sent_body = kwargs["content"].decode()
    assert 'xmlns="http://thalesgroup.com/RTTI/2017-10-01/ldb/"' in sent_body
    assert kwargs["headers"]["SOAPAction"] == (
        "http://thalesgroup.com/RTTI/2017-10-01/ldb/GetDepartureBoard"
    )


def test_trains_collector_surfaces_soap_fault_on_500():
    """A 500 from Darwin (e.g. an invalid access token) carries the real reason
    in a SOAP Fault body. The collector must surface that faultstring in its log
    instead of a bare 'Server error 500' — otherwise the cause is invisible."""
    import httpx
    from collectors.trains import TrainsCollector
    collector = TrainsCollector()
    collector.api_key = "bad-key"

    fault_body = (
        '<?xml version="1.0"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        "<soap:Body><soap:Fault>"
        "<faultcode>soap:Server</faultcode>"
        "<faultstring>Invalid Access Token supplied to the Web Service</faultstring>"
        "</soap:Fault></soap:Body></soap:Envelope>"
    )
    resp = MagicMock()
    resp.status_code = 500
    resp.text = fault_body
    resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock())
    )

    captured = []
    with patch("collectors.trains.httpx.post", return_value=resp), \
         patch("builtins.print", side_effect=lambda *a, **k: captured.append(" ".join(map(str, a)))):
        result = collector.collect()

    # No items, but the failure log must name the actual fault reason.
    assert result.items == []
    joined = "\n".join(captured)
    assert "Invalid Access Token" in joined
    assert "HTTP 500" in joined


def test_trains_collector_no_api_key_returns_empty():
    from collectors.trains import TrainsCollector
    collector = TrainsCollector()
    collector.api_key = ""
    result = collector.collect()
    assert result.source == "trains"
    assert result.items == []


# ── Roads collector (mocked) ──────────────────────────────────────────────

def test_roads_collector_parses_street_manager():
    from collectors.roads import RoadsCollector
    mock_activities = [
        {
            "street_name": "Station Road East",
            "activity_type": "Road closure",
            "promoter_organisation": "SES Water",
            "start_date": "2026-06-10T08:00:00Z",
            "end_date": "2026-06-14T17:00:00Z",
            "work_reference_number": "SW12345",
        }
    ]
    with patch("collectors.roads.httpx.get") as mock_get:
        # First call = Street Manager (returns activities); second = Surrey
        # bulletin (return empty HTML so it contributes nothing).
        sm = MagicMock()
        sm.json.return_value = mock_activities
        sm.raise_for_status = MagicMock()
        surrey = MagicMock()
        surrey.text = "<html><body></body></html>"
        surrey.raise_for_status = MagicMock()
        mock_get.side_effect = [sm, surrey]
        result = RoadsCollector().collect()

    assert result.source == "roads"
    assert len(result.items) == 1
    item = result.items[0]
    assert "Station Road East" in item.title
    assert item.data["promoter"] == "SES Water"
    assert item.data["start_date"] == "2026-06-10"
    assert item.data["end_date"] == "2026-06-14"
    assert item.url


def test_roads_collector_handles_network_error():
    from collectors.roads import RoadsCollector
    import httpx
    with patch("collectors.roads.httpx.get",
               side_effect=httpx.ConnectError("refused")):
        result = RoadsCollector().collect()
    assert result.source == "roads"
    assert result.items == []


def test_roads_collector_filters_surrey_to_tandridge():
    from collectors.roads import RoadsCollector
    import httpx
    surrey_html = """
      <ul>
        <li>A25 Oxted — resurfacing works</li>
        <li>High Street, Guildford — drainage</li>
        <li>Hurst Green level crossing — signal upgrade</li>
      </ul>
    """
    with patch("collectors.roads.httpx.get") as mock_get:
        def side_effect(url, *a, **k):
            if "streetmanager" in url:
                raise httpx.ConnectError("no street manager in test")
            resp = MagicMock()
            resp.text = surrey_html
            resp.raise_for_status = MagicMock()
            return resp
        mock_get.side_effect = side_effect
        result = RoadsCollector().collect()

    titles = " ".join(i.title for i in result.items).lower()
    assert "oxted" in titles
    assert "hurst green" in titles
    assert "guildford" not in titles


def test_roads_collector_uses_bulletin_deep_link():
    """When the bulletin links a road out to a live-map provider, the item must
    point at that specific closure rather than the generic listing page."""
    from collectors.roads import RoadsCollector, SURREY_BULLETIN
    import httpx
    surrey_html = """
      <ul>
        <li><a href="https://one.network/?GB/work/ABC123">Oxted, Station Road East</a> — gas works</li>
      </ul>
    """
    with patch("collectors.roads.httpx.get") as mock_get:
        def side_effect(url, *a, **k):
            if "streetmanager" in url:
                raise httpx.ConnectError("no street manager in test")
            resp = MagicMock()
            resp.text = surrey_html
            resp.raise_for_status = MagicMock()
            return resp
        mock_get.side_effect = side_effect
        result = RoadsCollector().collect()

    assert len(result.items) == 1
    item = result.items[0]
    assert item.url == "https://one.network/?GB/work/ABC123"
    assert item.url != SURREY_BULLETIN


def test_roads_collector_deep_links_named_road_to_map():
    """With no per-closure link available, a named road is searched on the
    one.network live map; vague prose falls back to one.network for the wider
    Oxted area (never the static council listing)."""
    from collectors.roads import RoadsCollector, SURREY_BULLETIN, ONE_NETWORK
    import httpx
    surrey_html = """
      <ul>
        <li>Limpsfield Road, Oxted — resurfacing</li>
        <li>Upcoming works across Tandridge this week</li>
      </ul>
    """
    with patch("collectors.roads.httpx.get") as mock_get:
        def side_effect(url, *a, **k):
            if "streetmanager" in url:
                raise httpx.ConnectError("no street manager in test")
            resp = MagicMock()
            resp.text = surrey_html
            resp.raise_for_status = MagicMock()
            return resp
        mock_get.side_effect = side_effect
        result = RoadsCollector().collect()

    by_road = {i.data["road"]: i.url for i in result.items}
    named = next(u for r, u in by_road.items() if r.startswith("Limpsfield Road"))
    assert named.startswith(ONE_NETWORK)
    assert "Limpsfield+Road" in named
    assert named != SURREY_BULLETIN

    vague = next(u for r, u in by_road.items() if r.lower().startswith("upcoming"))
    assert vague.startswith(ONE_NETWORK)
    assert vague != SURREY_BULLETIN
