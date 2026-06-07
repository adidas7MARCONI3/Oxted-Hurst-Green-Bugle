import anthropic
from dataclasses import dataclass
from datetime import datetime, timezone

from ..gatherers.rss import RawStory


@dataclass
class Article:
    title: str
    body: str
    source_url: str
    category: str
    generated_at: datetime = None

    def __post_init__(self):
        if self.generated_at is None:
            self.generated_at = datetime.now(timezone.utc)

    def to_markdown(self) -> str:
        ts = self.generated_at.strftime("%d %B %Y, %H:%M")
        return f"# {self.title}\n\n*{ts}*\n\n{self.body}\n\n---\n*Source: {self.source_url}*\n"


ARTICLE_SYSTEM_PROMPT = """\
You are a journalist for the Oxted & Hurst Green Bugle, a hyperlocal community newspaper \
serving Oxted and Hurst Green in Surrey, UK. Write concise, factual, friendly articles in \
the style of a quality local newspaper. Use plain English. Do not sensationalise. \
Keep articles between 150 and 300 words unless the story warrants more."""

ARTICLE_USER_PROMPT = """\
Rewrite the following story for the Oxted & Hurst Green Bugle. \
Ensure it is relevant to local residents. If it is not locally relevant, say only "NOT_LOCAL".

Title: {title}
Source: {source}
Summary: {summary}
URL: {url}"""


class ArticleWriter:
    def __init__(self, model: str = "claude-opus-4-8", max_tokens: int = 1024):
        self.client = anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    def write(self, story: RawStory) -> Article | None:
        message = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=ARTICLE_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": ARTICLE_USER_PROMPT.format(
                        title=story.title,
                        source=story.source,
                        summary=story.summary,
                        url=story.url,
                    ),
                }
            ],
        )
        body = message.content[0].text.strip()
        if body == "NOT_LOCAL":
            return None
        return Article(title=story.title, body=body, source_url=story.url, category=story.category)
