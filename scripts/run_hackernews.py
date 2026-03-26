#!/usr/bin/env python3
"""
Run Hacker News ingestion — collects AI-relevant stories and stores them.

Usage:
    python scripts/run_hackernews.py
    python scripts/run_hackernews.py --max-stories 30 --min-score 10 --dry-run

Flags:
    --max-stories N    Max stories to fetch (default: 60)
    --min-score N      Minimum HN score to include (default: 5)
    --no-comments      Skip fetching comments
    --dry-run          Collect but don't store to database
"""

import argparse
import asyncio
import json
import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import get_settings
from src.logging_config import setup_logging
from src.ingestion.hackernews import HackerNewsCollector
from src.ingestion.orchestrator import IngestionOrchestrator
from src.storage.postgres_client import PostgresClient


async def main():
    parser = argparse.ArgumentParser(description="Run Hacker News AI content collector")
    parser.add_argument("--max-stories", type=int, default=60, help="Max stories to fetch")
    parser.add_argument("--min-score", type=int, default=5, help="Minimum HN score")
    parser.add_argument("--no-comments", action="store_true", help="Skip comment collection")
    parser.add_argument("--dry-run", action="store_true", help="Collect only, don't store")
    args = parser.parse_args()

    setup_logging("INFO")
    settings = get_settings()

    # Configure the collector
    hn_config = {
        "max_stories": args.max_stories,
        "min_engagement": args.min_score,
        "include_comments": not args.no_comments,
        "max_comments_per_story": 3,
        "story_types": ["top", "best"],
    }

    collector = HackerNewsCollector(config=hn_config)

    if args.dry_run:
        # Dry run — collect and print, don't store
        print(f"\n Collecting from Hacker News (dry run)...")
        print(f"   Config: max_stories={args.max_stories}, min_score={args.min_score}\n")

        items = await collector.collect()

        print(f"\n{'='*70}")
        print(f" Collected {len(items)} AI-relevant items")
        print(f"   Filtered out: {collector.stats['filtered']}")
        print(f"   Errors: {collector.stats['errors']}")
        print(f"{'='*70}\n")

        for i, item in enumerate(items, 1):
            print(f"  {i:2d}. [{item.engagement_score:>4d} pts] {item.title}")
            print(f"      {item.source_url}")
            print(f"      Author: {item.author} | Published: {item.published_at.strftime('%Y-%m-%d %H:%M')}")
            ext_url = item.raw_metadata.get("external_url", "")
            if ext_url:
                print(f"      Link: {ext_url}")
            print()

        return

    # Full run — collect and store
    print(f"\n Running Hacker News ingestion...")
    print(f"   Config: max_stories={args.max_stories}, min_score={args.min_score}\n")

    db = PostgresClient(settings.supabase_db_url)
    await db.initialize()

    try:
        orchestrator = IngestionOrchestrator(db)
        summary = await orchestrator.run(sources=["hackernews"])

        print(f"\n{'='*70}")
        print(f"Ingestion Complete")
        print(f"{'='*70}")
        print(f"   Total collected: {summary['total_collected']}")
        print(f"   New items stored: {summary['total_stored']}")
        print(f"   Duration: {summary.get('run_duration_seconds', summary.get('elapsed_seconds', 0)):.1f}s")

        hn_stats = summary["by_source"].get("hackernews", {})
        print(f"\n   Hacker News breakdown:")
        print(f"     Collected: {hn_stats.get('collected', 0)}")
        print(f"     New: {hn_stats.get('new_inserted', 0)}")
        print(f"     Duplicates skipped: {hn_stats.get('duplicates_skipped', 0)}")
        print(f"     Filtered (not AI-relevant): {hn_stats.get('filtered', 0)}")
        print(f"     Errors: {hn_stats.get('errors', 0)}")

        # Show current DB count
        total_items = await db.get_item_count()
        print(f"\n   Total items in database: {total_items}")
        print()

    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
