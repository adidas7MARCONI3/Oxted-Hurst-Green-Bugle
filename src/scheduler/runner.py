import schedule
import time
from datetime import datetime, timezone

from rich.console import Console

from ..gatherers import RSSGatherer, WeatherGatherer
from ..writers import ArticleWriter, DigestWriter
from ..publishers import FilePublisher
from ..config import load_config

console = Console()


class Runner:
    def __init__(self, config_path: str = "config/settings.yaml"):
        self.cfg = load_config(config_path)
        self._setup_components()

    def _setup_components(self):
        import yaml
        with open("config/sources.yaml") as f:
            sources = yaml.safe_load(f)

        self.rss = RSSGatherer(sources.get("rss_feeds", []))
        wx_cfg = sources.get("weather", {})
        self.weather = WeatherGatherer(
            latitude=wx_cfg.get("latitude", 51.2572),
            longitude=wx_cfg.get("longitude", -0.0),
            timezone=wx_cfg.get("timezone", "Europe/London"),
        )
        llm_cfg = self.cfg["llm"]
        self.article_writer = ArticleWriter(model=llm_cfg["model"], max_tokens=llm_cfg["max_tokens"])
        self.digest_writer = DigestWriter(model=llm_cfg["model"])
        out = self.cfg["output"]

        self.publisher = FilePublisher(
            articles_dir=out["articles_dir"],
            digests_dir=out["digests_dir"],
        )

    def run_once(self):
        """Gather, write, and publish a single edition."""
        console.print("[bold]Oxted & Hurst Green Bugle[/bold] — running edition...")

        wx = None
        try:
            wx = self.weather.fetch_today()
            console.print(f"  Weather: {wx.description}")
        except Exception as exc:
            console.print(f"  [yellow]Weather unavailable:[/yellow] {exc}")

        stories = self.rss.fetch_all()
        console.print(f"  Fetched {len(stories)} stories from RSS")

        articles = []
        for story in stories[:20]:  # cap per run to control API spend
            try:
                article = self.article_writer.write(story)
                if article:
                    path = self.publisher.publish_article(article)
                    articles.append(article)
                    console.print(f"  [green]✓[/green] {article.title[:70]}")
            except Exception as exc:
                console.print(f"  [red]✗[/red] {story.title[:60]}: {exc}")

        if articles or wx:
            digest = self.digest_writer.write(articles, wx)
            path = self.publisher.publish_digest(digest)
            console.print(f"  [bold green]Digest published:[/bold green] {path}")

    def start(self):
        """Start the scheduled runner."""
        digest_time = self.cfg["schedule"]["digest_time"]
        interval_hours = self.cfg["schedule"]["article_interval_hours"]


        schedule.every().day.at(digest_time).do(self.run_once)
        schedule.every(interval_hours).hours.do(self.run_once)

        console.print(f"[bold]Bugle scheduler started.[/bold] Daily digest at {digest_time}.")
        while True:
            schedule.run_pending()
            time.sleep(60)
