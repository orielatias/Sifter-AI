"""
Ingestion orchestrator — runs all configured collectors and stores results.

This is the main entry point for the data collection pipeline.
It initializes each collector, runs them in sequence, deduplicates,
and stores everything in PostgreSQL.

Usage:
    python -m src.ingestion.orchestrator
    python -m src.ingestion.orchestrator hackernews rss
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import structlog

from src.config import get_settings
from src.logging_config import setup_logging
from src.models import ContentItem
from src.storage.postgres_client import PostgresClient

logger = structlog.get_logger()


class IngestionOrchestrator:
    """
    Coordinates all collectors and manages the ingestion pipeline.
    
    Runs collectors in sequence (to respect rate limits), handles errors
    gracefully (one broken collector doesn't stop others), and logs
    detailed stats for each run.
    """

    def __init__(self, db: PostgresClient, settings=None):
        self.db = db
        self.settings = settings or get_settings()
        self.run_stats = {
            "start_time": None,
            "end_time": None,
            "total_collected": 0,
            "total_stored": 0,
            "total_duplicates": 0,
            "total_errors": 0,
            "by_source": {},
        }

    async def run(self, sources: list[str] | None = None) -> dict:
        """
        Run the full ingestion pipeline.
        
        Args:
            sources: Optional list of source names to run. 
                     If None, runs all configured sources.
                     Valid: ["hackernews", "reddit", "rss", "youtube"]
        
        Returns:
            Dict with run statistics.
        """
        self.run_stats["start_time"] = datetime.now(timezone.utc)
        start = time.time()

        all_sources = sources or ["hackernews", "reddit", "rss", "youtube"]
        all_items: list[ContentItem] = []

        logger.info("ingestion.run_started", sources=all_sources)

        for source_name in all_sources:
            try:
                items = await self._run_collector(source_name)
                all_items.extend(items)

                self.run_stats["by_source"][source_name] = {
                    "collected": len(items),
                    "status": "success",
                }
            except Exception as e:
                self.run_stats["total_errors"] += 1
                self.run_stats["by_source"][source_name] = {
                    "collected": 0,
                    "status": "error",
                    "error": str(e),
                }
                logger.error("ingestion.collector_failed", source=source_name, error=str(e))

        self.run_stats["total_collected"] = len(all_items)

        # Store all items in the database
        if all_items:
            stored = await self.db.insert_content_items_batch(all_items)
            self.run_stats["total_stored"] = stored
            self.run_stats["total_duplicates"] = len(all_items) - stored

        self.run_stats["end_time"] = datetime.now(timezone.utc)
        elapsed = time.time() - start

        logger.info(
            "ingestion.run_complete",
            collected=self.run_stats["total_collected"],
            stored=self.run_stats["total_stored"],
            duplicates=self.run_stats["total_duplicates"],
            errors=self.run_stats["total_errors"],
            elapsed_seconds=round(elapsed, 1),
        )

        return self.run_stats

    async def _run_collector(self, source_name: str) -> list[ContentItem]:
        """Initialize and run a single collector by name."""
        logger.info("ingestion.collector_starting", source=source_name)

        if source_name == "hackernews":
            return await self._run_hackernews()
        elif source_name == "reddit":
            return await self._run_reddit()
        elif source_name == "rss":
            return await self._run_rss()
        elif source_name == "youtube":
            return await self._run_youtube()
        else:
            logger.warning("ingestion.unknown_source", source=source_name)
            return []

    async def _run_hackernews(self) -> list[ContentItem]:
        from src.ingestion.hackernews import HackerNewsCollector

        collector = HackerNewsCollector(config={
            "max_stories": 100,
            "min_engagement": 5,
        })
        return await collector.collect()

    async def _run_reddit(self) -> list[ContentItem]:
        if not self.settings.reddit_client_id:
            logger.warning("ingestion.reddit_not_configured",
                           hint="Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env")
            return []

        from src.ingestion.reddit import RedditCollector

        collector = RedditCollector(
            client_id=self.settings.reddit_client_id,
            client_secret=self.settings.reddit_client_secret,
            user_agent=self.settings.reddit_user_agent,
            config={
                "max_posts_per_sub": 25,
                "min_engagement": 10,
                "time_filter": "day",
            },
        )
        return await collector.collect()

    async def _run_rss(self) -> list[ContentItem]:
        from src.ingestion.rss import RSSCollector

        collector = RSSCollector(config={
            "max_age_days": 7,
            "max_entries_per_feed": 15,
        })
        return await collector.collect()

    async def _run_youtube(self) -> list[ContentItem]:
        if not self.settings.youtube_api_key:
            logger.warning("ingestion.youtube_not_configured",
                           hint="Set YOUTUBE_API_KEY in .env")
            return []

        from src.ingestion.youtube import YouTubeCollector

        collector = YouTubeCollector(
            api_key=self.settings.youtube_api_key,
            config={
                "max_per_channel": 5,
                "min_engagement": 1000,
                "fetch_transcripts": True,
            },
        )
        return await collector.collect()


async def main():
    """
    CLI entry point: run the full ingestion pipeline.
    
    Usage:
        python -m src.ingestion.orchestrator
        python -m src.ingestion.orchestrator hackernews rss
    """
    import sys

    setup_logging("INFO")
    settings = get_settings()

    # Optional: specify sources on command line
    sources = sys.argv[1:] if len(sys.argv) > 1 else None

    db = PostgresClient(settings.supabase_db_url)
    await db.initialize()

    try:
        orchestrator = IngestionOrchestrator(db, settings)
        stats = await orchestrator.run(sources=sources)

        print("\n" + "=" * 50)
        print("  Ingestion Run Summary")
        print("=" * 50)
        print(f"  Total collected:  {stats['total_collected']}")
        print(f"  New items stored: {stats['total_stored']}")
        print(f"  Duplicates:       {stats['total_duplicates']}")
        print(f"  Errors:           {stats['total_errors']}")
        print()
        for source, info in stats["by_source"].items():
            status = "✅" if info["status"] == "success" else "❌"
            print(f"  {status} {source}: {info['collected']} items")
        print("=" * 50)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
