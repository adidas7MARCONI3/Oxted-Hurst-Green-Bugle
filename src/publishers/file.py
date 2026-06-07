import os
from datetime import date
from pathlib import Path

from ..writers.article import Article
from ..writers.digest import Digest


class FilePublisher:
    def __init__(self, articles_dir: str, digests_dir: str):
        self.articles_dir = Path(articles_dir)
        self.digests_dir = Path(digests_dir)
        self.articles_dir.mkdir(parents=True, exist_ok=True)
        self.digests_dir.mkdir(parents=True, exist_ok=True)

    def publish_article(self, article: Article) -> Path:
        slug = self._slugify(article.title)
        ts = article.generated_at.strftime("%Y%m%d-%H%M")
        path = self.articles_dir / f"{ts}-{slug}.md"
        path.write_text(article.to_markdown(), encoding="utf-8")
        return path

    def publish_digest(self, digest: Digest) -> Path:
        date_str = digest.edition_date.strftime("%Y-%m-%d")
        path = self.digests_dir / f"{date_str}.md"
        path.write_text(digest.to_markdown(), encoding="utf-8")
        return path

    @staticmethod
    def _slugify(text: str) -> str:
        import re
        text = text.lower()
        text = re.sub(r"[^\w\s-]", "", text)
        text = re.sub(r"[\s_-]+", "-", text)
        return text[:60].strip("-")
