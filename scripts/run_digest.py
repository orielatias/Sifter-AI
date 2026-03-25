#!/usr/bin/env python3
"""
Generate and send the AI Intelligence Digest email.

Usage:
    python scripts/run_digest.py --dry-run          # Preview without sending
    python scripts/run_digest.py                     # Generate and send
    python scripts/run_digest.py --period-days 7     # Weekly digest
    python scripts/run_digest.py --top-n 15          # Top 15 signals
"""

import argparse
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import get_settings
from src.logging_config import setup_logging
from src.digest.generator import DigestGenerator
from src.storage.postgres_client import PostgresClient


async def main():
    parser = argparse.ArgumentParser(description="Generate and send AI Intelligence Digest")
    parser.add_argument("--period-days", type=int, default=3, help="Days of data to include")
    parser.add_argument("--top-n", type=int, default=10, help="Number of top signals")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending email")
    parser.add_argument("--save-html", type=str, default="", help="Save HTML to file")
    args = parser.parse_args()

    setup_logging("INFO")
    settings = get_settings()

    db = PostgresClient(settings.supabase_db_url)
    await db.initialize()

    try:
        generator = DigestGenerator(
            db=db,
            resend_api_key=settings.resend_api_key,
            from_email=settings.digest_from_email,
            to_emails=settings.digest_recipients,
        )

        print(f"\n📧 Generating AI Intelligence Digest...")
        print(f"   Period: last {args.period_days} day(s)")
        print(f"   Top signals: {args.top_n}")
        print(f"   Recipients: {settings.digest_recipients}")
        print(f"   Mode: {'DRY RUN' if args.dry_run else 'LIVE SEND'}\n")

        result = await generator.generate_and_send(
            period_days=args.period_days,
            top_n=args.top_n,
            dry_run=args.dry_run,
        )

        print(f"{'='*60}")
        print(f"{'📋 Digest Preview' if args.dry_run else 'Digest Sent'}")
        print(f"{'='*60}")
        print(f"   Status: {result['status']}")
        print(f"   Signals: {result.get('signals_count', 0)}")
        print(f"   Candidates analyzed: {result.get('total_candidates', 0)}")
        print(f"   Period: {result.get('period', 'N/A')}")

        if result.get("resend_id"):
            print(f"   Resend ID: {result['resend_id']}")

        if result.get("error"):
            print(f"   Error: {result['error']}")

        # Save HTML if requested or dry run
        if args.dry_run or args.save_html:
            html = result.get("html", "")
            if html:
                filename = args.save_html or "digest_preview.html"
                with open(filename, "w") as f:
                    f.write(html)
                print(f"\n   💾 HTML saved to: {filename}")
                print(f"   Open it in your browser to preview the email.")

        print()

    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())