#!/usr/bin/env python3
"""
Run the AI analysis pipeline — processes unanalyzed items through Claude.

Usage:
    python scripts/run_analysis.py
    python scripts/run_analysis.py --batch-size 20
    python scripts/run_analysis.py --batch-size 5 --dry-run
"""

import argparse
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import get_settings
from src.logging_config import setup_logging
from src.analysis.pipeline import AnalysisPipeline
from src.storage.postgres_client import PostgresClient


async def main():
    parser = argparse.ArgumentParser(description="Run Claude AI analysis pipeline")
    parser.add_argument("--batch-size", type=int, default=50, help="Items to process per run")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be processed")
    args = parser.parse_args()

    setup_logging("INFO")
    settings = get_settings()

    db = PostgresClient(settings.supabase_db_url)
    await db.initialize()

    try:
        if args.dry_run:
            # Just show unprocessed items
            items = await db.get_unprocessed_items(limit=args.batch_size)
            total = await db.get_item_count()

            print(f"\n🔍 Analysis Pipeline (dry run)")
            print(f"   Total items in DB: {total}")
            print(f"   Unprocessed items: {len(items)}")
            print(f"   Batch size: {args.batch_size}\n")

            if items:
                print(f"   Items that would be analyzed:")
                for i, item in enumerate(items[:20], 1):
                    title = (item.title or item.content_text[:60])[:70]
                    print(f"   {i:3d}. [{item.source_platform:>12s}] {title}")
                if len(items) > 20:
                    print(f"   ... and {len(items) - 20} more")
            print()
            return

        # Full run
        print(f"\n🧠 Running AI Analysis Pipeline...")
        print(f"   Model: Claude Haiku 4.5 (extraction)")
        print(f"   Batch size: {args.batch_size}")
        print(f"   Estimated cost: ~${args.batch_size * 0.001:.2f}\n")

        pipeline = AnalysisPipeline(
            api_key=settings.anthropic_api_key,
            db=db,
        )

        stats = await pipeline.run(batch_size=args.batch_size)

        print(f"\n{'='*60}")
        print(f"✅ Analysis Complete")
        print(f"{'='*60}")
        print(f"   Processed: {stats['processed']}")
        print(f"   Succeeded: {stats['succeeded']}")
        print(f"   Failed: {stats['failed']}")
        print(f"   Skipped: {stats['skipped']}")
        print(f"   Duration: {stats.get('duration_seconds', 0)}s")
        print(f"   Estimated cost: ~${stats['succeeded'] * 0.001:.3f}")

        # Show a few results
        analyzed = await db.query_items(min_relevance=1, limit=10)
        if analyzed:
            print(f"\n   📊 Sample analyzed items:")
            for item in analyzed[:10]:
                sentiment_emoji = {
                    "positive": "🟢",
                    "negative": "🔴",
                    "neutral": "⚪",
                    "mixed": "🟡",
                }.get(item.sentiment, "⚪")

                title = (item.title or "")[:55]
                print(f"   {sentiment_emoji} [{item.relevance_score or 0:>2d}/10] [{item.signal_type or 'other':>22s}] {title}")
                if item.summary:
                    print(f"      → {item.summary[:80]}")
        print()

    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())