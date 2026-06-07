import pytest
from pathlib import Path
from datetime import datetime, timezone, date

from src.publishers.file import FilePublisher
from src.writers.article import Article
from src.writers.digest import Digest


@pytest.fixture
def publisher(tmp_path):
    return FilePublisher(
        articles_dir=str(tmp_path / "articles"),
        digests_dir=str(tmp_path / "digests"),
    )


def make_article(**kwargs):
    defaults = dict(
        title="Oxted High Street reopens after works",
        body="The long-running roadworks on Oxted High Street concluded yesterday.",
        source_url="https://example.com/story",
        category="local_news",
        generated_at=datetime(2026, 6, 7, 9, 0, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return Article(**defaults)


def test_publish_article_creates_file(publisher):
    article = make_article()
    path = publisher.publish_article(article)
    assert path.exists()
    assert "oxted-high-street" in path.name
    assert "# Oxted High Street" in path.read_text()


def test_publish_digest_creates_file(publisher):
    digest = Digest(
        edition_date=date(2026, 6, 7),
        headline="A quiet Saturday in Surrey",
        body="Not much happened.",
        weather=None,
        articles=[make_article()],
    )
    path = publisher.publish_digest(digest)
    assert path.exists()
    assert path.name == "2026-06-07.md"
