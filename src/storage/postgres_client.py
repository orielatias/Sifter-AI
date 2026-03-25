"""
PostgreSQL database client using SQLAlchemy 2.0 async.

Provides typed methods for inserting, querying, and upserting content items,
entities, and digests. All operations are async and use connection pooling.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

import structlog
from sqlalchemy import select, update, func, desc, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models import ContentItem, Entity, ExtractedEntity, TopicTag
from src.storage.tables import Base, ContentItemRow, DigestRow, EntityRow

logger = structlog.get_logger()


class PostgresClient:
    """
    Async PostgreSQL client for the AI Intelligence Engine.
    
    Usage:
        client = PostgresClient(database_url)
        await client.initialize()  # Creates tables if needed
        await client.insert_content_item(item)
        results = await client.query_items(platform="reddit", limit=10)
        await client.close()
    """

    def __init__(self, database_url: str):
        self.engine = create_async_engine(
                    database_url,
                    echo=False,
                    pool_size=5,
                    max_overflow=10,
                    pool_pre_ping=True,
                    connect_args={
                        "statement_cache_size": 0,
                        "prepared_statement_cache_size": 0,
                    },
                )
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def initialize(self) -> None:
        """Create all tables if they don't exist."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("postgres.initialized", tables=list(Base.metadata.tables.keys()))

    async def close(self) -> None:
        """Dispose of the connection pool."""
        await self.engine.dispose()
        logger.info("postgres.closed")

    # ── Content Items ──────────────────────────────────────────────

    async def insert_content_item(self, item: ContentItem) -> bool:
        """
        Insert a content item. Returns True if inserted, False if duplicate (source_url).
        Uses ON CONFLICT DO NOTHING to handle duplicates gracefully.
        """
        async with self.session_factory() as session:
            stmt = pg_insert(ContentItemRow).values(
                id=item.id,
                source_platform=item.source_platform.value,
                source_url=item.source_url,
                author=item.author,
                title=item.title,
                content_text=item.content_text,
                published_at=item.published_at,
                collected_at=item.collected_at,
                engagement_score=item.engagement_score,
                relevance_score=item.relevance_score,
                sentiment=item.sentiment.value if item.sentiment else None,
                sentiment_confidence=item.sentiment_confidence,
                signal_type=item.signal_type.value if item.signal_type else None,
                summary=item.summary,
                entities=[e.model_dump() for e in item.entities] if item.entities else None,
                topics=[t.model_dump() for t in item.topics] if item.topics else None,
                raw_metadata=item.raw_metadata or None,
                embedding_id=item.embedding_id,
                cluster_id=item.cluster_id,
                is_top_signal=item.is_top_signal,
            ).on_conflict_do_nothing(constraint="uq_content_items_source_url")

            result = await session.execute(stmt)
            await session.commit()

            inserted = result.rowcount > 0
            if inserted:
                logger.info("postgres.item_inserted", item_id=item.id, url=item.source_url)
            else:
                logger.debug("postgres.item_duplicate", url=item.source_url)
            return inserted

    async def insert_content_items_batch(self, items: list[ContentItem]) -> int:
        """Insert multiple items in a single transaction. Returns count of new inserts."""
        inserted_count = 0
        async with self.session_factory() as session:
            for item in items:
                stmt = pg_insert(ContentItemRow).values(
                    id=item.id,
                    source_platform=item.source_platform.value,
                    source_url=item.source_url,
                    author=item.author,
                    title=item.title,
                    content_text=item.content_text,
                    published_at=item.published_at,
                    collected_at=item.collected_at,
                    engagement_score=item.engagement_score,
                    raw_metadata=item.raw_metadata or None,
                ).on_conflict_do_nothing(constraint="uq_content_items_source_url")
                result = await session.execute(stmt)
                inserted_count += result.rowcount

            await session.commit()
        logger.info("postgres.batch_inserted", total=len(items), new=inserted_count)
        return inserted_count

    async def update_item_analysis(
        self,
        item_id: str,
        relevance_score: int,
        sentiment: str,
        sentiment_confidence: float,
        signal_type: str,
        summary: str,
        entities: list[dict],
        topics: list[dict],
        embedding_id: str | None = None,
    ) -> None:
        """Update an item with AI analysis results."""
        async with self.session_factory() as session:
            stmt = (
                update(ContentItemRow)
                .where(ContentItemRow.id == item_id)
                .values(
                    relevance_score=relevance_score,
                    sentiment=sentiment,
                    sentiment_confidence=sentiment_confidence,
                    signal_type=signal_type,
                    summary=summary,
                    entities=entities,
                    topics=topics,
                    embedding_id=embedding_id,
                )
            )
            await session.execute(stmt)
            await session.commit()
            logger.debug("postgres.item_analysis_updated", item_id=item_id)

    async def get_unprocessed_items(self, limit: int = 100) -> list[ContentItemRow]:
        """Fetch items that haven't been analyzed yet (relevance_score is NULL)."""
        async with self.session_factory() as session:
            stmt = (
                select(ContentItemRow)
                .where(ContentItemRow.relevance_score.is_(None))
                .order_by(ContentItemRow.collected_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def query_items(
        self,
        platform: str | None = None,
        signal_type: str | None = None,
        min_relevance: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
    ) -> list[ContentItemRow]:
        """
        Query content items with optional filters.
        Returns items ordered by collected_at descending.
        """
        async with self.session_factory() as session:
            stmt = select(ContentItemRow)

            if platform:
                stmt = stmt.where(ContentItemRow.source_platform == platform)
            if signal_type:
                stmt = stmt.where(ContentItemRow.signal_type == signal_type)
            if min_relevance is not None:
                stmt = stmt.where(ContentItemRow.relevance_score >= min_relevance)
            if since:
                stmt = stmt.where(ContentItemRow.collected_at >= since)
            if until:
                stmt = stmt.where(ContentItemRow.collected_at <= until)

            stmt = stmt.order_by(desc(ContentItemRow.collected_at)).limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_top_signals(
        self,
        since: datetime,
        until: datetime,
        limit: int = 50,
    ) -> list[ContentItemRow]:
        """Get highest-relevance items in a time window for digest generation."""
        async with self.session_factory() as session:
            stmt = (
                select(ContentItemRow)
                .where(
                    ContentItemRow.collected_at >= since,
                    ContentItemRow.collected_at <= until,
                    ContentItemRow.relevance_score.isnot(None),
                )
                .order_by(desc(ContentItemRow.relevance_score), desc(ContentItemRow.engagement_score))
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_item_count(self) -> int:
        """Return total number of content items in the database."""
        async with self.session_factory() as session:
            stmt = select(func.count()).select_from(ContentItemRow)
            result = await session.execute(stmt)
            return result.scalar_one()

    # ── Entities ───────────────────────────────────────────────────

    async def upsert_entity(self, entity: Entity) -> None:
        """
        Insert or update an entity. On conflict (same name), increments mention_count.
        """
        async with self.session_factory() as session:
            stmt = pg_insert(EntityRow).values(
                name=entity.name,
                entity_type=entity.entity_type.value,
                first_seen_at=entity.first_seen_at,
                mention_count=entity.mention_count,
                extra_metadata=entity.metadata or None,
            ).on_conflict_do_update(
                index_elements=["name"],
                set_={
                    "mention_count": EntityRow.mention_count + 1,
                    "metadata": entity.metadata or EntityRow.extra_metadata,
                },
            )
            await session.execute(stmt)
            await session.commit()
            logger.debug("postgres.entity_upserted", name=entity.name)

    async def get_trending_entities(self, limit: int = 20) -> list[EntityRow]:
        """Get entities with the highest mention counts."""
        async with self.session_factory() as session:
            stmt = (
                select(EntityRow)
                .order_by(desc(EntityRow.mention_count))
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    # ── Digests ────────────────────────────────────────────────────

    async def insert_digest(
        self,
        period_start: datetime,
        period_end: datetime,
        signal_ids: list[str],
        total_items: int,
        report_html: str,
    ) -> int:
        """Insert a new digest record. Returns the digest ID."""
        async with self.session_factory() as session:
            row = DigestRow(
                period_start=period_start,
                period_end=period_end,
                signal_ids=signal_ids,
                total_items_processed=total_items,
                report_html=report_html,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            logger.info("postgres.digest_inserted", digest_id=row.id)
            return row.id

    async def mark_digest_sent(self, digest_id: int, recipient_count: int) -> None:
        """Mark a digest as sent."""
        async with self.session_factory() as session:
            stmt = (
                update(DigestRow)
                .where(DigestRow.id == digest_id)
                .values(
                    sent_at=datetime.now(timezone.utc),
                    recipient_count=recipient_count,
                )
            )
            await session.execute(stmt)
            await session.commit()
