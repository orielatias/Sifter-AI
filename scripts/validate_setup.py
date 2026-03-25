#!/usr/bin/env python3
"""
Quick validation script for Phase 1 setup.

Run this to verify your project is set up correctly:
    python scripts/validate_setup.py

It checks:
  1. Python version
  2. All required packages can be imported
  3. Pydantic models work
  4. Settings load from .env (if present)
  5. Database connectivity (if credentials are configured)
"""

import sys
import asyncio
from datetime import datetime, timezone


def check_python():
    v = sys.version_info
    print(f"  Python {v.major}.{v.minor}.{v.micro}", end="")
    if v.major == 3 and v.minor >= 12:
        print(" ✅")
        return True
    else:
        print(" ❌ (need 3.12+)")
        return False


def check_imports():
    packages = {
        "pydantic": "pydantic",
        "pydantic_settings": "pydantic-settings",
        "structlog": "structlog",
        "sqlalchemy": "sqlalchemy",
        "httpx": "httpx",
        "qdrant_client": "qdrant-client",
        "anthropic": "anthropic",
        "jinja2": "jinja2",
        "fastapi": "fastapi",
    }
    all_ok = True
    for module, pip_name in packages.items():
        try:
            __import__(module)
            print(f"  {pip_name} ✅")
        except ImportError:
            print(f"  {pip_name} ❌  →  pip install {pip_name}")
            all_ok = False
    return all_ok


def check_models():
    try:
        from src.models import (
            ContentItem, SourcePlatform, Sentiment, SignalType,
            ExtractedEntity, EntityType, ExtractionResult
        )

        item = ContentItem(
            source_platform=SourcePlatform.HACKERNEWS,
            source_url="https://news.ycombinator.com/item?id=test",
            content_text="Test content for validation",
            published_at=datetime(2026, 3, 15, tzinfo=timezone.utc),
        )
        assert item.id
        assert item.source_platform == SourcePlatform.HACKERNEWS

        data = item.model_dump()
        restored = ContentItem(**data)
        assert restored.id == item.id

        print("  Pydantic models ✅")
        return True
    except Exception as e:
        print(f"  Pydantic models ❌ — {e}")
        return False


def check_settings():
    try:
        from src.config import get_settings
        settings = get_settings()
        print(f"  Settings loaded ✅ (env: {settings.environment})")
        has_db = bool(settings.supabase_db_url and "supabase" in settings.supabase_db_url)
        has_qdrant = bool(settings.qdrant_url and "qdrant" in settings.qdrant_url)
        print(f"    Supabase configured: {'✅' if has_db else '⏳ not yet'}")
        print(f"    Qdrant configured:   {'✅' if has_qdrant else '⏳ not yet'}")
        print(f"    Anthropic configured: {'✅' if settings.anthropic_api_key.startswith('sk-') else '⏳ not yet'}")
        return True
    except Exception as e:
        print(f"  Settings ❌ — {e}")
        print("    (Copy .env.example to .env and fill in values)")
        return False


async def check_postgres():
    try:
        from src.config import get_settings
        settings = get_settings()
        if not settings.supabase_db_url or "supabase" not in settings.supabase_db_url:
            print("  PostgreSQL: ⏳ skipped (no SUPABASE_DB_URL)")
            return True

        from src.storage.postgres_client import PostgresClient
        client = PostgresClient(settings.supabase_db_url)
        await client.initialize()
        count = await client.get_item_count()
        await client.close()
        print(f"  PostgreSQL: ✅ connected ({count} items in DB)")
        return True
    except Exception as e:
        print(f"  PostgreSQL: ❌ — {e}")
        return False


def check_qdrant():
    try:
        from src.config import get_settings
        settings = get_settings()
        if not settings.qdrant_url or "qdrant" not in settings.qdrant_url:
            print("  Qdrant: ⏳ skipped (no QDRANT_URL)")
            return True

        from src.storage.qdrant_client import QdrantVectorClient
        client = QdrantVectorClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            dimension=settings.embedding_dimension,
        )
        client.initialize()
        info = client.get_collection_info()
        client.close()
        print(f"  Qdrant: ✅ connected ({info['points_count']} vectors)")
        return True
    except Exception as e:
        print(f"  Qdrant: ❌ — {e}")
        return False


def main():
    print("\n🔍 AI Intelligence Engine — Setup Validation\n")
    print("=" * 50)

    results = []

    print("\n1️⃣  Python Version")
    results.append(check_python())

    print("\n2️⃣  Package Imports")
    results.append(check_imports())

    print("\n3️⃣  Data Models")
    results.append(check_models())

    print("\n4️⃣  Configuration")
    results.append(check_settings())

    print("\n5️⃣  Database Connectivity")
    asyncio.run(check_postgres())
    check_qdrant()

    print("\n" + "=" * 50)
    if all(results):
        print("✅ Phase 1 foundation is ready!\n")
        print("Next steps:")
        print("  1. Create a Supabase project → paste DB URL into .env")
        print("  2. Create a Qdrant Cloud cluster → paste URL + API key into .env")
        print("  3. Run: python scripts/validate_setup.py  (again, to test connectivity)")
        print("  4. Run: pytest tests/test_phase1.py -v")
        print()
    else:
        print("⚠️  Some checks failed. Fix the issues above and re-run.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
