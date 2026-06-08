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


# ── Trains (Darwin OpenLDBWS) ─────────────────────────────────────────────

# A realistic Darwin response: the StationBoard child elements live in
# *several different* versioned `.../ldb/types` namespaces, NOT in the main
# ldb namespace. This is what previously broke namespace-exact parsing.
DARWIN_SAMPLE = b"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GetDepartureBoardResponse xmlns="http://thalesgroup.com/RTTI/2021-11-01/ldb/">
      <GetStationBoardResult
          xmlns:lt="http://thalesgroup.com/RTTI/2017-10-01/ldb/types"
          xmlns:lt4="http://thalesgroup.com/RTTI/2015-11-27/ldb/types">
        <lt4:locationName>Oxted</lt4:locationName>
        <lt4:crs>OXT</lt4:crs>
        <lt:trainServices>
          <lt:service>
            <lt4:std>08:15</lt4:std>
            <lt4:etd>On time</lt4:etd>
            <lt4:platform>2</lt4:platform>
            <lt4:operator>Southern</lt4:operator>
            <lt:destination>
              <lt4:location>
                <lt4:locationName>London Bridge</lt4:locationName>
              </lt4:location>
            </lt:destination>
          </lt:service>
          <lt:service>
            <lt4:std>08:32</lt4:std>
            <lt4:etd>Cancelled</lt4:etd>
            <lt4:operator>Southern</lt4:operator>
            <lt:isCancelled>true</lt:isCancelled>
            <lt:destination>
              <lt4:location>
                <lt4:locationName>Victoria</lt4:locationName>
              </lt4:location>
            </lt:destination>
          </lt:service>
        </lt:trainServices>
      </GetStationBoardResult>
    </GetDepartureBoardResponse>
  </soap:Body>
</soap:Envelope>"""


def test_trains_collector_parses_multi_namespace_response(monkeypatch):
    monkeypatch.setenv("DARWIN_API_KEY", "test-token")
    from collectors.trains import TrainsCollector

    with patch("collectors.trains.httpx.post") as mock_post:
        mock_post.return_value.content = DARWIN_SAMPLE
        mock_post.return_value.raise_for_status = MagicMock()
        result = TrainsCollector().collect()

    # Two stations (OXT, HGS) each return two services from the mock.
    assert result.source == "trains"
    assert len(result.items) == 4
    first = result.items[0]
    assert first.data["destination"] == "London Bridge"
    assert first.data["scheduled"] == "08:15"
    assert first.data["operator"] == "Southern"
    assert first.data["platform"] == "2"
    assert first.data["cancelled"] is False
    assert any(i.data["cancelled"] for i in result.items)


def test_trains_collector_no_api_key_returns_empty(monkeypatch):
    monkeypatch.delenv("DARWIN_API_KEY", raising=False)
    from collectors.trains import TrainsCollector
    result = TrainsCollector().collect()
    assert result.source == "trains"
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
