"""
RSS/Atom feed collector for AI blogs, newsletters, and VC feeds.

No authentication required — just a list of feed URLs.
Uses feedparser for robust parsing of RSS 2.0, Atom, and RDF feeds.
Uses sync httpx (same pattern as HN collector) for macOS compatibility.
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import feedparser
import structlog

from src.ingestion.base import BaseCollector
from src.models import ContentItem, SourcePlatform

logger = structlog.get_logger()

# ── Default AI-focused RSS feeds ──────────────────────────────────
# Curated list of high-signal sources. Add or remove as needed.
DEFAULT_FEEDS = [
    # Major AI labs
    {"url": "https://blog.openai.com/rss/", "name": "OpenAI Blog"},
    {"url": "https://www.anthropic.com/feed.xml", "name": "Anthropic Blog"},
    {"url": "https://blog.google/technology/ai/rss/", "name": "Google AI Blog"},
    {"url": "https://ai.meta.com/blog/rss/", "name": "Meta AI Blog"},
    {"url": "https://blogs.microsoft.com/ai/feed/", "name": "Microsoft AI Blog"},

    # AI news & analysis
    {"url": "https://techcrunch.com/category/artificial-intelligence/feed/", "name": "TechCrunch AI"},
    {"url": "https://the-decoder.com/feed/", "name": "The Decoder"},
    {"url": "https://www.marktechpost.com/feed/", "name": "MarkTechPost"},
    {"url": "https://syncedreview.com/feed/", "name": "Synced Review"},

    # AI newsletters & independent voices
    {"url": "https://jack-clark.net/feed/", "name": "Import AI (Jack Clark)"},
    {"url": "https://www.oneusefulthing.org/feed", "name": "One Useful Thing (Ethan Mollick)"},
    {"url": "https://simonwillison.net/atom/everything/", "name": "Simon Willison"},
    {"url": "https://lilianweng.github.io/index.xml", "name": "Lil'Log (Lilian Weng)"},
    {"url": "https://karpathy.github.io/feed.xml", "name": "Andrej Karpathy"},
    {"url": "https://www.latent.space/feed", "name": "Latent Space"},

    # VC & startup signals
    {"url": "https://a16z.com/feed/", "name": "a16z Blog"},
    {"url": "https://www.sequoiacap.com/feed/", "name": "Sequoia Capital"},
    {"url": "https://www.ycombinator.com/blog/rss/", "name": "Y Combinator Blog"},

    # Open source & developer
    {"url": "https://huggingface.co/blog/feed.xml", "name": "Hugging Face Blog"},
    {"url": "https://github.blog/feed/", "name": "GitHub Blog"},

    # Research
    {"url": "http://export.arxiv.org/rss/cs.AI", "name": "ArXiv cs.AI"},
    {"url": "http://export.arxiv.org/rss/cs.CL", "name": "ArXiv cs.CL"},
]


class RSSCollector(BaseCollector):
    """
    Collects AI-relevant content from RSS/Atom feeds.

    Configuration options (pass via config dict):
        feeds: list[dict] — list of {"url": ..., "name": ...} feed configs.
                             Defaults to DEFAULT_FEEDS if not provided.
        max_age_days: int — only collect entries published within this many days (default: 3)
        max_entries_per_feed: int — max entries to take from each feed (default: 10)
        filter_ai_keywords: bool — if True, apply AI keyword filter (default: True for general feeds)

    Usage:
        collector = RSSCollector(config={"max_age_days": 7})
        items = await collector.collect()
    """

    platform_name = "rss"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.feeds = self.config.get("feeds", DEFAULT_FEEDS)
        self.max_age_days = self.config.get("max_age_days", 3)
        self.max_entries = self.config.get("max_entries_per_feed", 10)
        self.filter_keywords = self.config.get("filter_ai_keywords", True)

    async def collect(self) -> list[ContentItem]:
        """Collect from all configured RSS feeds."""
        self._reset_stats()
        items = await asyncio.to_thread(self._collect_sync)
        self.stats["collected"] = len(items)
        self.log_collection_complete()
        return items

    def _collect_sync(self) -> list[ContentItem]:
        """Synchronous collection — runs in a thread."""
        items: list[ContentItem] = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.max_age_days)

        for feed_config in self.feeds:
            feed_url = feed_config["url"]
            feed_name = feed_config.get("name", feed_url)

            try:
                feed_items = self._process_feed(feed_url, feed_name, cutoff)
                items.extend(feed_items)
                logger.debug(
                    "collector.rss.feed_processed",
                    feed=feed_name,
                    entries=len(feed_items),
                )
            except Exception as e:
                self.stats["errors"] += 1
                logger.warning(
                    "collector.rss.feed_error",
                    feed=feed_name,
                    error=str(e),
                )

            # Small delay between feeds
            time.sleep(0.3)

        return items

    def _process_feed(
        self, feed_url: str, feed_name: str, cutoff: datetime
    ) -> list[ContentItem]:
        """Parse a single feed and return filtered ContentItems."""
        parsed = feedparser.parse(feed_url)

        if parsed.bozo and not parsed.entries:
            logger.warning(
                "collector.rss.parse_error",
                feed=feed_name,
                error=str(parsed.bozo_exception) if parsed.bozo_exception else "unknown",
            )
            return []

        items: list[ContentItem] = []

        for entry in parsed.entries[: self.max_entries]:
            # Extract publication date
            published_at = self._parse_date(entry)
            if not published_at:
                continue

            # Filter by age
            if published_at < cutoff:
                continue

            # Extract content
            title = entry.get("title", "").strip()
            link = entry.get("link", "")
            summary = self._extract_content(entry)
            author = self._extract_author(entry)

            if not title or not link:
                continue

            # Build full content text
            content_text = title
            if summary:
                content_text += f"\n\n{summary}"

            # AI keyword filter (skip for feeds that are inherently AI-focused)
            is_ai_focused_feed = self._is_ai_focused_feed(feed_name)
            if self.filter_keywords and not is_ai_focused_feed:
                if not self._has_ai_keywords(f"{title} {summary}"):
                    self.stats["filtered"] += 1
                    continue

            # Content length filter
            if not self._passes_content_filter(content_text):
                self.stats["filtered"] += 1
                continue

            item = ContentItem(
                source_platform=SourcePlatform.RSS,
                source_url=link,
                author=author,
                title=title,
                content_text=content_text,
                published_at=published_at,
                engagement_score=0,  # RSS doesn't have engagement metrics
                raw_metadata={
                    "feed_name": feed_name,
                    "feed_url": feed_url,
                    "tags": [t.get("term", "") for t in entry.get("tags", [])],
                },
            )
            items.append(item)

        return items

    def _parse_date(self, entry: dict) -> datetime | None:
        """Extract and parse publication date from a feed entry."""
        # Try structured date first (feedparser often parses this)
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            except Exception:
                pass

        if hasattr(entry, "updated_parsed") and entry.updated_parsed:
            try:
                return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
            except Exception:
                pass

        # Try raw date strings
        for field in ["published", "updated", "created"]:
            raw = entry.get(field, "")
            if raw:
                try:
                    return parsedate_to_datetime(raw).astimezone(timezone.utc)
                except Exception:
                    pass

        return None

    def _extract_content(self, entry: dict) -> str:
        """Extract the best available content text from a feed entry."""
        content = ""

        if entry.get("content"):
            content = entry["content"][0].get("value", "")
        elif entry.get("summary"):
            content = entry["summary"]
        elif entry.get("description"):
            content = entry["description"]

        return self._clean_html(content)

    @staticmethod
    def _extract_author(entry: dict) -> str:
        """Extract author name from entry."""
        if entry.get("author"):
            return entry["author"]
        if entry.get("authors") and len(entry["authors"]) > 0:
            return entry["authors"][0].get("name", "")
        return ""

    @staticmethod
    def _is_ai_focused_feed(feed_name: str) -> bool:
        """Check if a feed is inherently AI-focused (skip keyword filtering)."""
        ai_feeds = {
            "openai", "anthropic", "google ai", "meta ai", "microsoft ai",
            "deepmind", "hugging face", "arxiv cs.ai", "arxiv cs.cl",
            "import ai", "latent space", "the decoder", "marktechpost",
            "synced", "lil'log", "karpathy", "one useful thing",
        }
        return any(kw in feed_name.lower() for kw in ai_feeds)

    @staticmethod
    def _clean_html(html_text: str) -> str:
        """Strip HTML tags and clean up text."""
        if not html_text:
            return ""
        text = re.sub(r"<(br|p|div|h[1-6]|li)[^>]*>", "\n", html_text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = (
            text.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
            .replace("&#39;", "'")
            .replace("&nbsp;", " ")
        )
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" {2,}", " ", text)
        return text.strip()