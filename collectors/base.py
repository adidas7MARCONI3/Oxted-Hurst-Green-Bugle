import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Item:
    id: str
    title: str
    description: str
    date: str          # ISO 8601
    category: str
    url: str = ""
    headline: str = ""  # filled by summariser
    summary: str = ""   # filled by summariser
    data: dict = field(default_factory=dict)


@dataclass
class CollectionResult:
    source: str
    collected_at: str
    items: list[Item]

    def save(self, output_dir: str = "data/output") -> Path:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        path = Path(output_dir) / f"{self.source}.json"
        path.write_text(
            json.dumps(
                {"source": self.source, "collected_at": self.collected_at,
                 "items": [asdict(i) for i in self.items]},
                indent=2,
            ),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, source: str, output_dir: str = "data/output") -> "CollectionResult":
        path = Path(output_dir) / f"{source}.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            source=raw["source"],
            collected_at=raw["collected_at"],
            items=[Item(**i) for i in raw["items"]],
        )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BaseCollector(ABC):
    name: str = ""

    @abstractmethod
    def collect(self) -> CollectionResult:
        ...

    def run(self, output_dir: str = "data/output") -> CollectionResult:
        result = self.collect()
        path = result.save(output_dir)
        print(f"[{self.name}] {len(result.items)} items → {path}")
        return result
