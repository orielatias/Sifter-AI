"""
Core data models for the AI Intelligence Engine.

These Pydantic models define the normalized schema that every piece of
content is transformed into, regardless of which platform it came from.
They are used for validation, serialization, and as the contract between
pipeline stages.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────

class SourcePlatform(StrEnum):
    REDDIT = "reddit"
    HACKERNEWS = "hackernews"
    TWITTER = "twitter"
    YOUTUBE = "youtube"
    RSS = "rss"
    ARXIV = "arxiv"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"
    PRODUCTHUNT = "producthunt"
    GITHUB = "github"
    OTHER = "other"


class Sentiment(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class SignalType(StrEnum):
    PRODUCT_LAUNCH = "product_launch"
    FUNDING_ROUND = "funding_round"
    RESEARCH_BREAKTHROUGH = "research_breakthrough"
    TOOL_RELEASE = "tool_release"
    TREND_SHIFT = "trend_shift"
    OPINION_ANALYSIS = "opinion_analysis"
    TUTORIAL = "tutorial"
    HIRING_SIGNAL = "hiring_signal"
    PARTNERSHIP = "partnership"
    REGULATORY = "regulatory"
    ACQUISITION = "acquisition"
    OPEN_SOURCE = "open_source"
    BENCHMARK = "benchmark"
    OTHER = "other"


class EntityType(StrEnum):
    COMPANY = "company"
    PERSON = "person"
    PRODUCT = "product"
    FRAMEWORK = "framework"
    PAPER = "paper"
    ORGANIZATION = "organization"
    MODEL = "model"


# ── Sub-models ─────────────────────────────────────────────────────

class ExtractedEntity(BaseModel):
    """A single entity extracted by the AI analysis pipeline."""
    name: str
    entity_type: EntityType
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)


class TopicTag(BaseModel):
    """Topic classification with two-level taxonomy."""
    level1: str  # e.g., "Companies & Startups"
    level2: str  # e.g., "funding_round"
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)


# ── Primary Content Model ──────────────────────────────────────────

class ContentItem(BaseModel):
    """
    The normalized representation of a single piece of collected content.
    
    This is the core data model that flows through the entire pipeline:
    ingestion → analysis → storage → retrieval.
    """
    # Identity
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    
    # Source metadata
    source_platform: SourcePlatform
    source_url: str
    author: str = ""
    title: str | None = None
    content_text: str
    
    # Timestamps
    published_at: datetime
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Engagement
    engagement_score: int = 0  # Normalized engagement metric
    
    # AI-generated fields (populated by analysis pipeline)
    relevance_score: int | None = Field(default=None, ge=1, le=10)
    sentiment: Sentiment | None = None
    sentiment_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    signal_type: SignalType | None = None
    summary: str | None = None
    entities: list[ExtractedEntity] = Field(default_factory=list)
    topics: list[TopicTag] = Field(default_factory=list)
    
    # Storage references
    embedding_id: str | None = None
    cluster_id: int | None = None
    is_top_signal: bool = False
    
    # Raw platform-specific metadata (preserved for flexibility)
    raw_metadata: dict = Field(default_factory=dict)


# ── Entity Registry Model ─────────────────────────────────────────

class Entity(BaseModel):
    """
    Normalized entity in the registry. Tracks mentions over time
    so we can identify trending companies, people, tools, etc.
    """
    id: int | None = None
    name: str
    entity_type: EntityType
    first_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    mention_count: int = 1
    metadata: dict = Field(default_factory=dict)  # website, funding_stage, etc.


# ── Digest Model ───────────────────────────────────────────────────

class DigestSignal(BaseModel):
    """A single signal as it appears in the email digest."""
    rank: int
    title: str
    summary: str
    sentiment: Sentiment
    signal_type: SignalType
    source_urls: list[str] = Field(default_factory=list)
    source_platforms: list[str] = Field(default_factory=list)


class Digest(BaseModel):
    """A complete intelligence digest report."""
    id: int | None = None
    period_start: datetime
    period_end: datetime
    signals: list[DigestSignal] = Field(default_factory=list)
    trending_entities: list[dict] = Field(default_factory=list)
    emerging_patterns: str = ""
    total_items_processed: int = 0
    report_html: str = ""
    sent_at: datetime | None = None
    recipient_count: int = 0


# ── Analysis Pipeline Models ──────────────────────────────────────

class ExtractionResult(BaseModel):
    """
    The structured output expected from Claude Haiku extraction.
    This is what the LLM returns for each content item.
    """
    entities: list[ExtractedEntity] = Field(default_factory=list)
    topics: list[TopicTag] = Field(default_factory=list)
    sentiment: Sentiment = Sentiment.NEUTRAL
    sentiment_confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    signal_type: SignalType = SignalType.OTHER
    relevance_score: int = Field(ge=1, le=10, default=5)
    summary: str = ""


class ClusterInfo(BaseModel):
    """Represents a detected topic cluster."""
    cluster_id: int
    label: str = ""
    item_count: int = 0
    avg_relevance: float = 0.0
    top_entities: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    is_cross_platform: bool = False
