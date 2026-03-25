"""
Hacker News collector using the official Firebase API.

Uses the SYNC httpx client (wrapped in asyncio.to_thread) because the async
httpx client has TLS compatibility issues on macOS + Python 3.13.

API docs: https://github.com/HackerNewsAPI/API
- No authentication required
- No strict rate limit (be respectful — small delays between requests)
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone

import httpx
import structlog

from src.ingestion.base import BaseCollector
from src.models import ContentItem, SourcePlatform

logger = structlog.get_logger()

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"


def _sync_get_json(url: str) -> dict | list | None:
    """Synchronous HTTP GET that returns parsed JSON."""
    try:
        resp = httpx.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.debug("hackernews.sync_get_error", url=url, error=str(e))
        return None


class HackerNewsCollector(BaseCollector):
    """
    Collects AI-relevant stories and top comments from Hacker News.

    Configuration options (pass via config dict):
        max_stories: int — max stories to fetch per run (default: 60)
        min_engagement: int — minimum score threshold (default: 5)
        max_comments_per_story: int — top comments to grab (default: 3)
        story_types: list — which feeds to pull (default: ["top", "best"])
        include_comments: bool — whether to collect comments (default: True)

    Usage:
        collector = HackerNewsCollector(config={"max_stories": 30, "min_engagement": 10})
        items = await collector.collect()
    """

    platform_name = "hackernews"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.max_stories = self.config.get("max_stories", 60)
        self.min_engagement = self.config.get("min_engagement", 5)
        self.max_comments = self.config.get("max_comments_per_story", 3)
        self.story_types = self.config.get("story_types", ["top", "best"])
        self.include_comments = self.config.get("include_comments", True)

    async def collect(self) -> list[ContentItem]:
        """
        Main collection method. Runs sync HTTP calls in a thread pool
        to avoid blocking the event loop while working around async TLS issues.
        """
        self._reset_stats()
        items = await asyncio.to_thread(self._collect_sync)
        self.stats["collected"] = len(items)
        self.log_collection_complete()
        return items

    def _collect_sync(self) -> list[ContentItem]:
        """Synchronous collection logic — runs in a thread."""
        items: list[ContentItem] = []

        # 1. Get story IDs from each feed type
        story_ids = self._get_story_ids()
        logger.info("collector.hackernews.story_ids_fetched", total_ids=len(story_ids))

        # 2. Fetch and process each story
        for story_id in story_ids:
            try:
                result = self._fetch_and_process_story(story_id)
                if result:
                    items.append(result)
            except Exception as e:
                self.stats["errors"] += 1
                logger.warning("collector.hackernews.story_error", story_id=story_id, error=str(e))

            # Small delay to be respectful
            time.sleep(0.15)

        return items

    def _get_story_ids(self) -> list[int]:
        """Fetch story IDs from configured feeds, deduplicated."""
        all_ids: set[int] = set()

        for story_type in self.story_types:
            url = f"{HN_API_BASE}/{story_type}stories.json"
            data = _sync_get_json(url)
            if data and isinstance(data, list):
                per_feed_limit = self.max_stories // len(self.story_types)
                all_ids.update(data[:per_feed_limit])
                logger.debug(
                    "collector.hackernews.feed_fetched",
                    feed=story_type,
                    count=min(len(data), per_feed_limit),
                )
            else:
                self.stats["errors"] += 1
                logger.error("collector.hackernews.feed_error", feed=story_type)

        return list(all_ids)

    def _fetch_and_process_story(self, story_id: int) -> ContentItem | None:
        """Fetch a single story and its top comments. Returns a ContentItem or None."""
        story = _sync_get_json(f"{HN_API_BASE}/item/{story_id}.json")
        if not story or story.get("type") != "story":
            return None

        # Extract fields
        title = story.get("title", "")
        url = story.get("url", "")
        hn_url = f"https://news.ycombinator.com/item?id={story_id}"
        score = story.get("score", 0)
        author = story.get("by", "")
        timestamp = story.get("time", 0)
        text = story.get("text", "")  # Self-posts have text
        num_comments = story.get("descendants", 0)

        # Build content text
        content_parts = [title]
        if text:
            content_parts.append(self._clean_html(text))
        content_text = "\n\n".join(content_parts)

        # Filter: must be AI-relevant
        search_text = f"{title} {text} {url}".lower()
        if not self._has_ai_keywords(search_text):
            self.stats["filtered"] += 1
            return None

        # Filter: engagement threshold
        if not self._passes_engagement_filter(score):
            self.stats["filtered"] += 1
            return None

        # Collect top comments for richer context
        if self.include_comments and story.get("kids"):
            comment_texts = self._fetch_top_comments(story["kids"])
            if comment_texts:
                content_text += "\n\n--- Top Comments ---\n" + "\n\n".join(comment_texts)

        # Filter: content length
        if not self._passes_content_filter(content_text):
            self.stats["filtered"] += 1
            return None

        return ContentItem(
            source_platform=SourcePlatform.HACKERNEWS,
            source_url=hn_url,
            author=author,
            title=title,
            content_text=content_text,
            published_at=datetime.fromtimestamp(timestamp, tz=timezone.utc),
            engagement_score=score,
            raw_metadata={
                "hn_id": story_id,
                "external_url": url,
                "score": score,
                "num_comments": num_comments,
                "type": "story",
            },
        )

    def _fetch_top_comments(self, kid_ids: list[int]) -> list[str]:
        """Fetch the top N direct comments on a story."""
        comments = []
        for kid_id in kid_ids[: self.max_comments]:
            time.sleep(0.1)
            comment = _sync_get_json(f"{HN_API_BASE}/item/{kid_id}.json")
            if comment and comment.get("text") and not comment.get("deleted"):
                author = comment.get("by", "anonymous")
                text = self._clean_html(comment["text"])
                if len(text) > 20:
                    comments.append(f"[{author}]: {text}")
        return comments

    @staticmethod
    def _clean_html(html_text: str) -> str:
        """Strip HTML tags from HN comment text."""
        text = html_text.replace("<p>", "\n\n")
        text = re.sub(r"<[^>]+>", "", text)
        text = (
            text.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
            .replace("&#x27;", "'")
            .replace("&#x2F;", "/")
        )
        return text.strip()