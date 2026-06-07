from .cricket import CricketCollector
from .football import FootballCollector
from .hockey import HockeyCollector
from ..base import BaseCollector, CollectionResult, now_iso


class SportsCollector(BaseCollector):
    name = "sports"

    def collect(self) -> CollectionResult:
        items = []
        for cls in (CricketCollector, FootballCollector, HockeyCollector):
            try:
                result = cls().collect()
                items.extend(result.items)
            except Exception as exc:
                print(f"[sports] {cls.__name__} failed: {exc}")
        items.sort(key=lambda x: x.date, reverse=True)
        return CollectionResult(source=self.name, collected_at=now_iso(), items=items)
