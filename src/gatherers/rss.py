import feedparser
import httpx
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class RawStory:
    title: str
    summary: str
    url: str
    source: str
    category: str
    published: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class RSSGatherer:
    def __init__(self, feeds: list[dict]):
        self.feeds = feeds

    def fetch_all(self) -> list[RawStory]:
        stories = []
        for feed_cfg in self.feeds:
            try:
                stories.extend(self._fetch_feed(feed_cfg))
            except Exception as exc:
                print(f"[rss] failed to fetch {feed_cfg['name']}: {exc}")
        return stories

    def _fetch_feed(self, feed_cfg: dict) -> list[RawStory]:
        parsed = feedparser.parse(feed_cfg["url"])
        stories = []
        for entry in parsed.entries:
            published = self._parse_date(entry)
            stories.append(
                RawStory(
                    title=entry.get("title", ""),
                    summary=entry.get("summary", entry.get("description", "")),
                    url=entry.get("link", ""),
                    source=feed_cfg["name"],
                    category=feed_cfg.get("category", "general"),
                    published=published,
                )
            )
        return stories

    @staticmethod
    def _parse_date(entry) -> datetime:
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            import time
            return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        return datetime.now(timezone.utc)
