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


def test_crime_collector_deduplicates_incidents():
    from collectors.crime import CrimeCollector
    # Same crime returned multiple times: once by duplicate id, once by
    # duplicate persistent_id. Only the first occurrence of each should survive.
    mock_crimes = [
        {"id": 1, "persistent_id": "abc", "category": "burglary",
         "location": {"street": {"name": "High Street"}},
         "outcome_status": None, "month": "2026-05"},
        {"id": 1, "persistent_id": "abc", "category": "burglary",
         "location": {"street": {"name": "High Street"}},
         "outcome_status": None, "month": "2026-05"},
        {"id": 2, "persistent_id": "def", "category": "theft",
         "location": {"street": {"name": "Station Road"}},
         "outcome_status": None, "month": "2026-05"},
        {"id": 99, "persistent_id": "def", "category": "theft",
         "location": {"street": {"name": "Station Road"}},
         "outcome_status": None, "month": "2026-05"},
    ]
    with patch("collectors.crime.httpx.get") as mock_get:
        mock_get.return_value.json.return_value = mock_crimes
        mock_get.return_value.raise_for_status = MagicMock()
        result = CrimeCollector().collect()

    # Four input rows collapse to two unique incidents.
    assert len(result.items) == 2


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


# ── Roads collector — Street Manager Open Data (keyless, mocked) ───────────

def _roads_collector():
    from collectors.roads import RoadsCollector
    return RoadsCollector()


def _mock_resp(json_value=None, text=""):
    resp = MagicMock()
    if json_value is None:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_value
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


def test_roads_collector_parses_open_data_works():
    # Open-data event records wrap the permit under `object_data`.
    mock_works = [
        {
            "event_type": "WORK_START",
            "object_data": {
                "street_name": "Station Road West, Oxted",
                "town": "Oxted",
                "activity_type": "Road closure",
                "work_category": "Major",
                "promoter_organisation": "Thames Water",
                "traffic_management_type": "Full road closure with diversion via A25",
                "permit_status": "granted",
                "usrn": "12345678",
                "work_reference_number": "TW-2026-ABC123",
                "proposed_start_date": "2026-06-08T08:00:00Z",
                "proposed_end_date": "2026-06-12T17:00:00Z",
            },
        }
    ]
    with patch("collectors.roads.httpx.get") as mock_get:
        mock_get.return_value = _mock_resp(json_value={"works": mock_works})
        result = _roads_collector().collect()

    # The request hits the keyless open-data feed with no Authorization header.
    _, kwargs = mock_get.call_args
    assert "Authorization" not in kwargs.get("headers", {})
    assert "opendata.streetmanager.service.gov.uk" in mock_get.call_args[0][0]

    assert result.source == "roads"
    assert len(result.items) == 1
    item = result.items[0]
    d = item.data
    assert d["street_name"] == "Station Road West, Oxted"
    assert d["work_type"] == "Road closure"
    assert d["work_category"] == "Major"
    assert d["promoter"] == "Thames Water"
    assert d["status"] == "Planned"
    assert d["start_date"] == "2026-06-08"
    assert d["end_date"] == "2026-06-12"
    assert d["source"] == "Street Manager Open Data"
    # Dates formatted "Mon 8 June – Fri 12 June".
    assert d["dates"] == "Mon 8 June – Fri 12 June"
    # Both required deep links.
    assert d["one_network_url"] == "https://one.network/?USRN=12345678"
    assert d["street_manager_url"] == (
        "https://streetmanager.dft.gov.uk/works/TW-2026-ABC123"
    )
    assert item.url == d["street_manager_url"]
    # Summary reads like the brief's template.
    assert item.description == (
        "Station Road West, Oxted will be closed from Mon 8 June to Fri 12 June "
        "for major works by Thames Water. "
        "Full road closure with diversion via A25."
    )


def test_roads_collector_parses_ndjson():
    """The feed may be newline-delimited JSON rather than a single array."""
    line = json.dumps({
        "object_data": {
            "street_name": "High Street, Oxted", "town": "Oxted",
            "usrn": "1", "work_reference_number": "A",
        }
    })
    with patch("collectors.roads.httpx.get") as mock_get:
        mock_get.return_value = _mock_resp(json_value=None, text=line + "\n")
        result = _roads_collector().collect()
    assert len(result.items) == 1
    assert result.items[0].data["street_name"] == "High Street, Oxted"


def test_roads_collector_handles_network_error():
    import httpx
    with patch("collectors.roads.httpx.get",
               side_effect=httpx.ConnectError("refused")):
        result = _roads_collector().collect()
    assert result.source == "roads"
    assert result.items == []


def test_roads_collector_filters_to_oxted_area():
    """The national feed is filtered to Oxted client-side: by 3 km radius when a
    record carries coordinates, and by area-name otherwise. Records that are
    neither near Oxted nor mention it are dropped."""
    mock_works = [
        {"street_name": "High Street, Oxted", "usrn": "1",
         "work_reference_number": "A", "latitude": 51.2570, "longitude": -0.0050},
        {"street_name": "North Street, Guildford", "usrn": "2",
         "work_reference_number": "B", "latitude": 51.2360, "longitude": -0.5800},
        {"street_name": "Mill Lane", "town": "Hurst Green",
         "usrn": "3", "work_reference_number": "C"},
        {"street_name": "Bridge Road", "town": "Reigate",
         "usrn": "4", "work_reference_number": "D"},
    ]
    with patch("collectors.roads.httpx.get") as mock_get:
        mock_get.return_value = _mock_resp(json_value=mock_works)
        result = _roads_collector().collect()

    roads = [i.data["street_name"] for i in result.items]
    assert "High Street, Oxted" in roads     # within 3 km
    assert "Mill Lane" in roads              # area-name match (Hurst Green)
    assert "North Street, Guildford" not in roads  # outside 3 km
    assert "Bridge Road" not in roads        # no coords, no area match


def test_roads_collector_categories_and_status():
    """Immediate/urgent works map to Emergency; permit statuses and actual dates
    map onto Planned / In progress / Completed."""
    from collectors.roads import _normalise_category, _normalise_status
    assert _normalise_category("Immediate - urgent") == "Emergency"
    assert _normalise_category("Major") == "Major"
    assert _normalise_category("Standard") == "Standard"
    # Permit statuses from the open-data feed.
    assert _normalise_status("granted", {}) == "Planned"
    assert _normalise_status("progressing", {}) == "In progress"
    assert _normalise_status("closed", {}) == "Completed"
    # Derived status: an actual start with no end ⇒ In progress.
    assert _normalise_status("", {"actual_start_date": "2026-06-01"}) == "In progress"
    assert _normalise_status("", {}) == "Planned"


# ── Council collector (mocked) ────────────────────────────────────────────

TANDRIDGE_NEWS_HTML = """
<html><body>
  <header><a href="/cookies">Cookie policy</a><a href="/search">Search</a></header>
  <main id="main-content">
    <ul class="news-list">
      <li>
        <a href="/Your-council/News/Council-tax-support-1-June-2026">
          Council tax support scheme expanded</a>
        <span class="date">1 June 2026</span>
      </li>
      <li>
        <a href="/Your-council/News/Recycling-changes">
          Recycling collection changes for residents</a>
        <time datetime="2026-05-20">20 May 2026</time>
      </li>
    </ul>
  </main>
  <footer><a href="/privacy">Privacy</a></footer>
</body></html>
"""

TANDRIDGE_MEETINGS_HTML = """
<html><body>
  <main role="main">
    <table>
      <tr><th>Committee</th></tr>
      <tr><td>
        <a href="/Your-council/Meetings-and-decisions/Planning-Committee-2026-06-15">
          Planning Committee agenda</a> 2026-06-15
      </td></tr>
    </table>
  </main>
</body></html>
"""

OXTED_PC_HTML = """
<html><body>
  <article>
    <p><a href="/meetings/full-council-02-06-2026/">
      Full Council Meeting minutes</a> 02/06/2026</p>
    <p><a href="https://oxted-pc.org.uk/meetings/planning-12-06-2026/">
      Planning Sub-Committee agenda</a> 12 June 2026</p>
  </article>
</body></html>
"""


def _council_response(html):
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status = MagicMock()
    return resp


def test_council_collector_scrapes_all_sources():
    from collectors.council import CouncilCollector, NEWS_URL, MEETINGS_URL, OXTED_PC_URL

    def side_effect(url, *a, **k):
        if url == NEWS_URL:
            return _council_response(TANDRIDGE_NEWS_HTML)
        if url == MEETINGS_URL:
            return _council_response(TANDRIDGE_MEETINGS_HTML)
        if url == OXTED_PC_URL:
            return _council_response(OXTED_PC_HTML)
        raise AssertionError(f"unexpected url {url}")

    with patch("collectors.council.httpx.get", side_effect=side_effect):
        result = CouncilCollector().collect()

    assert result.source == "council"
    # 2 news + 1 meeting + 2 Oxted PC = 5 items, chrome links filtered out.
    assert len(result.items) == 5

    by_url = {i.url: i for i in result.items}
    # Every item has an absolute, working URL on the correct host.
    assert all(i.url.startswith("http") for i in result.items)
    assert "https://www.tandridge.gov.uk/Your-council/News/Recycling-changes" in by_url

    # Dates are extracted from text / surrounding markup; newest first.
    dates = [i.date for i in result.items]
    assert dates == sorted(dates, reverse=True)
    assert "2026-06-15" in dates  # ISO from meetings table
    assert "2026-06-01" in dates  # "1 June 2026" from news

    # Oxted PC items are tagged local; relative href resolved to absolute.
    pc = [i for i in result.items if i.data["source"] == "oxted_pc"]
    assert len(pc) == 2
    assert all(i.data["local"] for i in pc)
    assert any(i.url == "http://oxted-pc.org.uk/meetings/full-council-02-06-2026/"
               for i in pc)
    # No cookie/privacy/search chrome leaked through.
    assert not any("cookie" in i.url.lower() or "privacy" in i.url.lower()
                   for i in result.items)


def test_council_collector_one_source_failure_isolated():
    """A single failing source must not sink the others."""
    import httpx
    from collectors.council import CouncilCollector, NEWS_URL, OXTED_PC_URL

    def side_effect(url, *a, **k):
        if url == NEWS_URL:
            raise httpx.ConnectError("news down")
        if url == OXTED_PC_URL:
            return _council_response(OXTED_PC_HTML)
        return _council_response("<html><body><main></main></body></html>")

    with patch("collectors.council.httpx.get", side_effect=side_effect):
        result = CouncilCollector().collect()

    # News blew up, meetings empty, but Oxted PC still yields its 2 items.
    assert len(result.items) == 2
    assert all(i.data["source"] == "oxted_pc" for i in result.items)


def test_council_collector_handles_network_error():
    from collectors.council import CouncilCollector
    import httpx
    with patch("collectors.council.httpx.get",
               side_effect=httpx.ConnectError("refused")):
        result = CouncilCollector().collect()
    assert result.source == "council"
    assert result.items == []
