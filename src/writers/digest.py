import anthropic
from dataclasses import dataclass
from datetime import date, datetime, timezone

from .article import Article
from ..gatherers.weather import WeatherSummary


@dataclass
class Digest:
    edition_date: date
    headline: str
    body: str
    weather: WeatherSummary | None
    articles: list[Article]

    def to_markdown(self) -> str:
        date_str = self.edition_date.strftime("%A %-d %B %Y")
        lines = [
            f"# The Oxted & Hurst Green Bugle",
            f"### {date_str}",
            "",
        ]
        if self.weather:
            lines += [f"**Today's weather:** {self.weather.description}", ""]
        lines += [f"## {self.headline}", "", self.body, ""]
        for article in self.articles:
            lines += [f"---", f"### {article.title}", "", article.body, ""]
        return "\n".join(lines)


DIGEST_SYSTEM_PROMPT = """\
You are the editor of the Oxted & Hurst Green Bugle. Write a short morning briefing \
(100–150 words) summarising the day's local news for residents of Oxted and Hurst Green, \
Surrey. Be warm, informative, and community-focused."""

DIGEST_USER_PROMPT = """\
Today is {date}. Weather: {weather}.

Stories in today's edition:
{story_list}

Write the morning briefing and suggest a headline (prefix it with HEADLINE: on its own line, \
then the briefing text on the next line)."""


class DigestWriter:
    def __init__(self, model: str = "claude-opus-4-8", max_tokens: int = 512):
        self.client = anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    def write(self, articles: list[Article], weather: WeatherSummary | None) -> Digest:
        today = date.today()
        weather_str = weather.description if weather else "not available"
        story_list = "\n".join(f"- {a.title}" for a in articles) or "No stories today."

        message = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=DIGEST_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": DIGEST_USER_PROMPT.format(
                        date=today.strftime("%A %-d %B %Y"),
                        weather=weather_str,
                        story_list=story_list,
                    ),
                }
            ],
        )
        raw = message.content[0].text.strip()
        headline, body = self._parse_response(raw)
        return Digest(edition_date=today, headline=headline, body=body, weather=weather, articles=articles)

    @staticmethod
    def _parse_response(raw: str) -> tuple[str, str]:
        lines = raw.splitlines()
        headline = "Today in Oxted & Hurst Green"
        body_lines = []
        for i, line in enumerate(lines):
            if line.startswith("HEADLINE:"):
                headline = line.removeprefix("HEADLINE:").strip()
                body_lines = lines[i + 1 :]
                break
        else:
            body_lines = lines
        return headline, "\n".join(body_lines).strip()
