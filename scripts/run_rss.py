#!/usr/bin/env python3
"""
Run RSS feed ingestion — collects AI content from blogs, newsletters, and labs.

Usage:
    python scripts/run_rss.py --dry-run
    python scripts/run_rss.py
    python scripts/run_rss.py --max-age-days 7
"""

import argparse
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import get_settings
from src.logging_config import setup_logging
from src.ingestion.rss import RSSCollector
from src.storage.postgres_client import PostgresClient


async def main():
    parser = argparse.ArgumentParser(description="Run RSS feed AI content collector")
    parser.add_argument("--max-age-days", type=int, default=3, help="Max age of entries in days")
    parser.add_argument("--max-entries", type=int, default=10, help="Max entries per feed")
    parser.add_argument("--dry-run", action="store_true", help="Collect only, don't store")
    args = parser.parse_args()

    setup_logging("INFO")
    settings = get_settings()

    rss_config = {
        "max_age_days": args.max_age_days,
        "max_entries_per_feed": args.max_entries,
    }

    collector = RSSCollector(config=rss_config)

    if args.dry_run:
        print(f"\n🔍 Collecting from RSS feeds (dry run)...")
        print(f"   Config: max_age_days={args.max_age_days}, max_entries={args.max_entries}")
        print(f"   Feeds: {len(collector.feeds)} configured\n")

        items = await collector.collect()

        print(f"\n{'='*70}")
        print(f"📊 Collected {len(items)} items from RSS feeds")
        print(f"   Filtered out: {collector.stats['filtered']}")
        print(f"   Errors: {collector.stats['errors']}")
        print(f"{'='*70}\n")

        # Group by feed
        by_feed: dict[str, list] = {}
        for item in items:
            feed = item.raw_metadata.get("feed_name", "Unknown")
            by_feed.setdefault(feed, []).append(item)

        for feed_name, feed_items in sorted(by_feed.items()):
            print(f"  📰 {feed_name} ({len(feed_items)} items)")
            for item in feed_items:
                date_str = item.published_at.strftime("%Y-%m-%d")
                print(f"     • [{date_str}] {item.title[:80]}")
                print(f"       {item.source_url}")
            print()

        return

    # Full run
    print(f"\n🚀 Running RSS ingestion...")
    print(f"   Feeds: {len(collector.feeds)} configured\n")

    db = PostgresClient(settings.supabase_db_url)
    await db.initialize()

    try:
        items = await collector.collect()

        new_count = 0
        if items:
            new_count = await db.insert_content_items_batch(items)

        total_items = await db.get_item_count()

        print(f"\n{'='*70}")
        print(f"RSS Ingestion Complete")
        print(f"{'='*70}")
        print(f"   Collected: {len(items)}")
        print(f"   New items stored: {new_count}")
        print(f"   Duplicates skipped: {len(items) - new_count}")
        print(f"   Filtered: {collector.stats['filtered']}")
        print(f"   Errors: {collector.stats['errors']}")
        print(f"\n   📦 Total items in database: {total_items}")
        print()

    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())