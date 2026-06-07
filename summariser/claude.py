"""Claude-powered summariser — rewrites raw collector data into plain English
headlines and summaries fit for a local newspaper.
"""
import anthropic
from collectors.base import CollectionResult, Item

SYSTEM = """\
You are a subeditor for the Oxted & Hurst Green Bugle, a hyperlocal newspaper \
serving Oxted and Hurst Green, Surrey (RH8). Your job is to write crisp, factual, \
friendly copy in plain English. Sentences should be short. No jargon. \
Do not sensationalise. Residents are your audience — local relevance is paramount."""

ITEM_PROMPT = """\
Write a newspaper headline and a two-sentence summary for the following item.

Category: {category}
Title: {title}
Description: {description}

Respond in exactly this format (no other text):
HEADLINE: <headline here>
SUMMARY: <two sentences here>"""


class Summariser:
    def __init__(self, model: str = "claude-opus-4-8", max_tokens: int = 256):
        self.client = anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    def enrich(self, result: CollectionResult) -> CollectionResult:
        """Add headline and summary to each item via Claude."""
        enriched = []
        for item in result.items:
            try:
                item = self._enrich_item(item)
            except Exception as exc:
                print(f"[summariser] failed for '{item.title[:40]}': {exc}")
            enriched.append(item)
        result.items = enriched
        return result

    def _enrich_item(self, item: Item) -> Item:
        message = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM,
            messages=[{
                "role": "user",
                "content": ITEM_PROMPT.format(
                    category=item.category,
                    title=item.title,
                    description=item.description[:600],
                ),
            }],
        )
        raw = message.content[0].text.strip()
        headline, summary = self._parse(raw, item)
        item.headline = headline
        item.summary = summary
        return item

    @staticmethod
    def _parse(raw: str, item: Item) -> tuple[str, str]:
        headline = item.title
        summary = item.description
        for line in raw.splitlines():
            if line.startswith("HEADLINE:"):
                headline = line.removeprefix("HEADLINE:").strip()
            elif line.startswith("SUMMARY:"):
                summary = line.removeprefix("SUMMARY:").strip()
        return headline, summary

    def enrich_batch(self, results: list[CollectionResult]) -> list[CollectionResult]:
        return [self.enrich(r) for r in results]
