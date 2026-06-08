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


# ── Council collector (mocked HTML) ───────────────────────────────────────

_TANDRIDGE_NEWS_HTML = """
<html><body>
<header><a href="/">Home</a><a href="/search">Search</a></header>
<main>
  <ul class="news-list">
    <li><a href="/Your-council/News/new-leisure-centre-opens">New leisure centre opens in Oxted</a>
        <span class="date">3 June 2026</span></li>
    <li><a href="/Your-council/News/council-tax-2026">Council tax bills for 2026/27</a>
        <time>2026-05-28</time></li>
  </ul>
</main>
<footer><a href="/privacy">Privacy</a><a href="/cookies">Cookie policy</a></footer>
</body></html>
"""

_TANDRIDGE_MEETINGS_HTML = """
<html><body>
<main>
  <div class="meetings">
    <a href="/Your-council/Meetings-and-decisions/Meetings/Planning-Committee-12-June-2026">
        Planning Committee — 12 June 2026 (agenda)</a>
    <a href="/Your-council/Meetings-and-decisions/Meetings/Full-Council-1-July-2026">
        Full Council meeting — 1 July 2026</a>
  </div>
</main>
</body></html>
"""

_OXTED_PC_HTML = """
<html><body>
<main>
  <article>
    <a href="/wp-content/uploads/2026/06/agenda-june.pdf">Parish Council Meeting Agenda — 10 June 2026</a>
    <a href="/wp-content/uploads/2026/05/minutes-may.pdf">Minutes of meeting held 13 May 2026</a>
  </article>
</main>
</body></html>
"""


def _mock_soup_getter(url_to_html):
    """Return a fake _get_soup that maps a URL substring to canned HTML."""
    from bs4 import BeautifulSoup

    def _getter(url):
        for needle, html in url_to_html.items():
            if needle in url:
                return BeautifulSoup(html, "html.parser")
        return None
    return _getter


def test_council_collector_scrapes_all_sources():
    from collectors.council import (
        CouncilCollector, NEWS_URL, MEETINGS_URL, OXTED_PC_URL,
    )
    mapping = {
        NEWS_URL: _TANDRIDGE_NEWS_HTML,
        MEETINGS_URL: _TANDRIDGE_MEETINGS_HTML,
        OXTED_PC_URL: _OXTED_PC_HTML,
    }
    with patch.object(CouncilCollector, "_get_soup",
                      staticmethod(_mock_soup_getter(mapping))):
        result = CouncilCollector().collect()

    assert result.source == "council"
    # 2 news + 2 meetings + 2 parish = 6 items
    assert len(result.items) == 6

    # Every item must have a working absolute URL.
    for item in result.items:
        assert item.url.startswith("http"), item.url
        assert item.category == "council"

    # Dates parsed from text, sorted newest first.
    dates = [i.date for i in result.items]
    assert dates == sorted(dates, reverse=True)
    assert "2026-07-01" in dates  # Full Council 1 July
    assert "2026-06-12" in dates  # Planning Committee 12 June

    # Relative hrefs resolved against the Tandridge host.
    news = [i for i in result.items if i.data.get("source") == "tandridge_news"]
    assert any("tandridge.gov.uk/Your-council/News/" in i.url for i in news)

    # Oxted PC items tagged as hyperlocal.
    pc = [i for i in result.items if i.data.get("source") == "oxted_pc"]
    assert pc and all(i.data.get("local") for i in pc)


def test_council_collector_one_source_failure_isolated():
    """If one source raises, the others still return items."""
    from collectors.council import CouncilCollector, MEETINGS_URL, OXTED_PC_URL

    def _getter(url):
        from bs4 import BeautifulSoup
        if MEETINGS_URL in url:
            return BeautifulSoup(_TANDRIDGE_MEETINGS_HTML, "html.parser")
        if OXTED_PC_URL in url:
            return BeautifulSoup(_OXTED_PC_HTML, "html.parser")
        raise RuntimeError("news source down")

    with patch.object(CouncilCollector, "_get_soup", staticmethod(_getter)):
        result = CouncilCollector().collect()

    # News failed, but meetings (2) + parish (2) survived.
    assert len(result.items) == 4
    sources = {i.data.get("source") for i in result.items}
    assert sources == {"tandridge_meetings", "oxted_pc"}


def test_council_collector_handles_network_error():
    from collectors.council import CouncilCollector
    import httpx
    with patch("collectors.council.httpx.get",
               side_effect=httpx.ConnectError("refused")):
        result = CouncilCollector().collect()
    assert result.source == "council"
    assert result.items == []
