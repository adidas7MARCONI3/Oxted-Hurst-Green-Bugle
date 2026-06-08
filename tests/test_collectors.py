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
