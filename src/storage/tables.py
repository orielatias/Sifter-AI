"""
SQLAlchemy table definitions for the PostgreSQL schema.

These mirror the schema defined in the architecture document (Section 6.1).
Uses SQLAlchemy 2.0 style with mapped_column and async engine support.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class ContentItemRow(Base):
    """
    Primary table: every collected and processed content item.
    """
    __tablename__ = "content_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_platform: Mapped[str] = mapped_column(String(50), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(String(255), default="")
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Timestamps
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Engagement
    engagement_score: Mapped[int] = mapped_column(Integer, default=0)

    # AI-generated fields
    relevance_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sentiment_confidence: Mapped[float | None] = mapped_column(nullable=True)
    signal_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    entities: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    topics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    raw_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Storage references
    embedding_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cluster_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_top_signal: Mapped[bool] = mapped_column(Boolean, default=False)

    # Row timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # ── Indexes ──
    __table_args__ = (
        UniqueConstraint("source_url", name="uq_content_items_source_url"),
        Index("ix_content_items_collected_at", "collected_at"),
        Index("ix_content_items_platform_collected", "source_platform", "collected_at"),
        Index("ix_content_items_relevance", "relevance_score", "collected_at"),
        Index("ix_content_items_signal_type", "signal_type", "collected_at"),
        Index("ix_content_items_is_top_signal", "is_top_signal"),
    )


class EntityRow(Base):
    """
    Normalized entity registry for tracking mentions over time.
    """
    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    mention_count: Mapped[int] = mapped_column(Integer, default=1)
    extra_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)


class DigestRow(Base):
    """
    Tracks each generated intelligence digest report.
    """
    __tablename__ = "digests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    signal_ids: Mapped[list | None] = mapped_column(ARRAY(String(36)), nullable=True)
    total_items_processed: Mapped[int] = mapped_column(Integer, default=0)
    report_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recipient_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
