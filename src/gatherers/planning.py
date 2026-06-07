import httpx
import re
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class PlanningApplication:
    reference: str
    address: str
    description: str
    status: str
    received: datetime
    url: str


class PlanningGatherer:
    """Fetches planning applications from Tandridge District Council."""

    SEARCH_URL = "https://www.tandridge.gov.uk/Planning-and-building/Planning-applications/Search-for-planning-applications"

    def __init__(self, search_pattern: str = "Oxted|Hurst Green"):
        self.search_pattern = re.compile(search_pattern, re.IGNORECASE)

    def fetch_recent(self, days: int = 7) -> list[PlanningApplication]:
        """Return planning applications from the last `days` days."""
        # Tandridge uses a public search portal; scraping logic goes here.
        # Returning empty list until scraping is implemented for the specific portal.
        return []

    def _is_local(self, address: str) -> bool:
        return bool(self.search_pattern.search(address))
