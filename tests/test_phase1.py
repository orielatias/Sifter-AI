"""
Phase 1 Milestone Tests — AI Intelligence Engine

These tests verify:
1. Pydantic models validate and serialize correctly
2. PostgreSQL client can insert and retrieve content items
3. Qdrant client can upsert and search embeddings
4. Full round-trip: create item → store → retrieve

Run with: pytest tests/test_phase1.py -v

NOTE: Tests marked with @pytest.mark.integration require live database
connections. Set the environment variables in .env before running them.
For local development without databases, the unit tests (unmarked) will
pass without any external dependencies.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest

from src.models import (
    ContentItem,
    Digest,
    DigestSignal,
    Entity,
    EntityType,
    ExtractionResult,
    ExtractedEntity,
    Sentiment,
    SignalType,
    SourcePlatform,
    TopicTag,
)


# ══════════════════════════════════════════════
# UNIT TESTS — No external dependencies needed
# ══════════════════════════════════════════════


class TestContentItemModel:
    """Verify the core ContentItem Pydantic model."""

    def test_create_minimal_item(self):
        """Minimum required fields should produce a valid item."""
        item = ContentItem(
            source_platform=SourcePlatform.HACKERNEWS,
            source_url="https://news.ycombinator.com/item?id=12345",
            content_text="Show HN: A new AI agent framework",
            published_at=datetime(2026, 3, 15, tzinfo=timezone.utc),
        )
        assert item.id  # UUID auto-generated
        assert item.source_platform == SourcePlatform.HACKERNEWS
        assert item.relevance_score is None  # Not yet analyzed
        assert item.sentiment is None
        assert item.entities == []
        assert item.is_top_signal is False

    def test_create_fully_analyzed_item(self):
        """An item with all AI-generated fields populated."""
        item = ContentItem(
            source_platform=SourcePlatform.REDDIT,
            source_url="https://reddit.com/r/MachineLearning/comments/abc123",
            author="researcher42",
            title="New paper: Scaling Laws for AI Agents",
            content_text="We just published a paper showing that agent capabilities follow predictable scaling laws...",
            published_at=datetime(2026, 3, 14, 10, 30, tzinfo=timezone.utc),
            engagement_score=847,
            relevance_score=9,
            sentiment=Sentiment.POSITIVE,
            sentiment_confidence=0.92,
            signal_type=SignalType.RESEARCH_BREAKTHROUGH,
            summary="New research demonstrates predictable scaling laws for AI agent capabilities.",
            entities=[
                ExtractedEntity(name="DeepMind", entity_type=EntityType.COMPANY, confidence=0.95),
                ExtractedEntity(name="GPT-5", entity_type=EntityType.MODEL, confidence=0.7),
            ],
            topics=[
                TopicTag(level1="Research & Papers", level2="new_model_architecture", confidence=0.88),
            ],
            raw_metadata={"subreddit": "MachineLearning", "num_comments": 134},
        )
        assert item.relevance_score == 9
        assert len(item.entities) == 2
        assert item.entities[0].name == "DeepMind"
        assert item.topics[0].level1 == "Research & Papers"

    def test_relevance_score_validation(self):
        """Relevance score must be between 1 and 10."""
        with pytest.raises(Exception):
            ContentItem(
                source_platform=SourcePlatform.HACKERNEWS,
                source_url="https://example.com",
                content_text="test",
                published_at=datetime.now(timezone.utc),
                relevance_score=11,  # Invalid
            )

    def test_serialization_round_trip(self):
        """Model should serialize to dict and back without data loss."""
        item = ContentItem(
            source_platform=SourcePlatform.TWITTER,
            source_url="https://x.com/karpathy/status/123",
            author="karpathy",
            content_text="Hot take on AI agents",
            published_at=datetime(2026, 3, 15, tzinfo=timezone.utc),
            sentiment=Sentiment.MIXED,
            signal_type=SignalType.OPINION_ANALYSIS,
            entities=[
                ExtractedEntity(name="OpenAI", entity_type=EntityType.COMPANY),
            ],
        )
        data = item.model_dump()
        restored = ContentItem(**data)
        assert restored.id == item.id
        assert restored.source_platform == item.source_platform
        assert restored.entities[0].name == "OpenAI"

    def test_default_collected_at(self):
        """collected_at should auto-populate to ~now."""
        before = datetime.now(timezone.utc)
        item = ContentItem(
            source_platform=SourcePlatform.RSS,
            source_url="https://blog.anthropic.com/post/123",
            content_text="Anthropic releases Claude 5",
            published_at=datetime(2026, 3, 15, tzinfo=timezone.utc),
        )
        after = datetime.now(timezone.utc)
        assert before <= item.collected_at <= after


class TestExtractionResultModel:
    """Verify the model that Claude Haiku returns."""

    def test_valid_extraction(self):
        result = ExtractionResult(
            entities=[
                ExtractedEntity(name="Mistral", entity_type=EntityType.COMPANY, confidence=0.9),
                ExtractedEntity(name="Mixtral-Next", entity_type=EntityType.MODEL, confidence=0.85),
            ],
            topics=[
                TopicTag(level1="LLMs & Models", level2="model_release", confidence=0.95),
            ],
            sentiment=Sentiment.POSITIVE,
            sentiment_confidence=0.88,
            signal_type=SignalType.PRODUCT_LAUNCH,
            relevance_score=8,
            summary="Mistral releases Mixtral-Next, a new MoE model beating GPT-4 on benchmarks.",
        )
        assert result.relevance_score == 8
        assert len(result.entities) == 2
        assert result.signal_type == SignalType.PRODUCT_LAUNCH

    def test_default_extraction(self):
        """Empty extraction should have safe defaults."""
        result = ExtractionResult()
        assert result.entities == []
        assert result.sentiment == Sentiment.NEUTRAL
        assert result.relevance_score == 5


class TestEntityModel:
    def test_create_entity(self):
        entity = Entity(
            name="Anthropic",
            entity_type=EntityType.COMPANY,
            mention_count=42,
            metadata={"website": "https://anthropic.com", "funding_stage": "Series D"},
        )
        assert entity.name == "Anthropic"
        assert entity.mention_count == 42


class TestDigestModel:
    def test_create_digest(self):
        digest = Digest(
            period_start=datetime(2026, 3, 14, tzinfo=timezone.utc),
            period_end=datetime(2026, 3, 15, tzinfo=timezone.utc),
            signals=[
                DigestSignal(
                    rank=1,
                    title="Claude 5 Released",
                    summary="Anthropic launches Claude 5 with breakthrough agent capabilities.",
                    sentiment=Sentiment.POSITIVE,
                    signal_type=SignalType.PRODUCT_LAUNCH,
                    source_urls=["https://anthropic.com/claude-5"],
                    source_platforms=["rss", "reddit", "twitter"],
                ),
            ],
            total_items_processed=1247,
            emerging_patterns="AI agent frameworks are converging around MCP as a standard protocol.",
        )
        assert len(digest.signals) == 1
        assert digest.signals[0].rank == 1
        assert digest.total_items_processed == 1247


class TestEnumValues:
    """Verify all enums serialize to clean strings."""

    def test_source_platforms(self):
        assert SourcePlatform.REDDIT.value == "reddit"
        assert SourcePlatform.HACKERNEWS.value == "hackernews"
        assert SourcePlatform.TWITTER.value == "twitter"

    def test_signal_types(self):
        assert SignalType.FUNDING_ROUND.value == "funding_round"
        assert SignalType.RESEARCH_BREAKTHROUGH.value == "research_breakthrough"

    def test_sentiments(self):
        assert Sentiment.POSITIVE.value == "positive"
        assert Sentiment.MIXED.value == "mixed"


# ══════════════════════════════════════════════
# INTEGRATION TESTS — Require live databases
# ══════════════════════════════════════════════
# Run with: pytest tests/test_phase1.py -v -m integration
#
# These require SUPABASE_DB_URL and QDRANT_URL/QDRANT_API_KEY
# to be set in your .env file.

integration = pytest.mark.skipif(
    not os.environ.get("SUPABASE_DB_URL"),
    reason="SUPABASE_DB_URL not set — skipping integration tests",
)


@integration
class TestPostgresIntegration:
    """Integration tests against a real Supabase PostgreSQL instance."""

    @pytest.fixture
    async def pg_client(self):
        from src.storage.postgres_client import PostgresClient
        client = PostgresClient(os.environ["SUPABASE_DB_URL"])
        await client.initialize()
        yield client
        await client.close()

    async def test_insert_and_retrieve(self, pg_client):
        """Insert a content item and retrieve it by platform."""
        test_url = f"https://test.example.com/{uuid.uuid4()}"
        item = ContentItem(
            source_platform=SourcePlatform.HACKERNEWS,
            source_url=test_url,
            author="testuser",
            title="Test: AI Agent Framework",
            content_text="This is a test item for the integration test suite.",
            published_at=datetime(2026, 3, 15, tzinfo=timezone.utc),
            engagement_score=100,
        )

        # Insert
        inserted = await pg_client.insert_content_item(item)
        assert inserted is True

        # Duplicate should return False
        inserted_again = await pg_client.insert_content_item(item)
        assert inserted_again is False

        # Retrieve
        results = await pg_client.query_items(platform="hackernews", limit=5)
        assert len(results) > 0
        found = any(r.source_url == test_url for r in results)
        assert found, f"Inserted item not found in query results"

    async def test_item_count(self, pg_client):
        """Should be able to count items."""
        count = await pg_client.get_item_count()
        assert isinstance(count, int)
        assert count >= 0

    async def test_upsert_entity(self, pg_client):
        """Insert an entity and verify mention count increments."""
        entity = Entity(
            name=f"TestCorp-{uuid.uuid4().hex[:8]}",
            entity_type=EntityType.COMPANY,
            metadata={"test": True},
        )
        await pg_client.upsert_entity(entity)
        # Upsert again — mention_count should increment
        await pg_client.upsert_entity(entity)

        trending = await pg_client.get_trending_entities(limit=100)
        found = [e for e in trending if e.name == entity.name]
        assert len(found) == 1
        assert found[0].mention_count >= 2


qdrant_integration = pytest.mark.skipif(
    not os.environ.get("QDRANT_URL"),
    reason="QDRANT_URL not set — skipping Qdrant integration tests",
)


@qdrant_integration
class TestQdrantIntegration:
    """Integration tests against a real Qdrant Cloud instance."""

    @pytest.fixture
    def qdrant_client(self):
        from src.storage.qdrant_client import QdrantVectorClient
        client = QdrantVectorClient(
            url=os.environ["QDRANT_URL"],
            api_key=os.environ.get("QDRANT_API_KEY", ""),
            collection_name="test_content_embeddings",
            dimension=128,  # Small dimension for testing
        )
        client.initialize()
        yield client
        # Cleanup: delete test collection
        try:
            client.client.delete_collection("test_content_embeddings")
        except Exception:
            pass
        client.close()

    def test_upsert_and_search(self, qdrant_client):
        """Insert vectors and retrieve them via similarity search."""
        import random

        # Create 5 test points with random vectors
        points = []
        for i in range(5):
            vec = [random.random() for _ in range(128)]
            points.append({
                "id": str(uuid.uuid4()),
                "vector": vec,
                "payload": {
                    "source_platform": "reddit" if i % 2 == 0 else "hackernews",
                    "signal_type": "product_launch",
                    "sentiment": "positive",
                    "relevance_score": 5 + i,
                    "summary": f"Test item {i}",
                },
            })

        qdrant_client.upsert_embeddings_batch(points)

        # Search with the first point's vector
        results = qdrant_client.search(
            query_vector=points[0]["vector"],
            top_k=3,
        )
        assert len(results) > 0
        assert results[0]["score"] > 0.9  # Should find itself

    def test_filtered_search(self, qdrant_client):
        """Search with metadata filters."""
        import random

        point_id = str(uuid.uuid4())
        vec = [random.random() for _ in range(128)]
        qdrant_client.upsert_embedding(
            point_id=point_id,
            vector=vec,
            payload={
                "source_platform": "twitter",
                "signal_type": "funding_round",
                "sentiment": "positive",
                "relevance_score": 9,
            },
        )

        # Search with filter
        results = qdrant_client.search(
            query_vector=vec,
            top_k=5,
            platform="twitter",
            signal_type="funding_round",
        )
        assert len(results) > 0
        assert results[0]["source_platform"] == "twitter"

    def test_collection_info(self, qdrant_client):
        """Should return collection stats."""
        info = qdrant_client.get_collection_info()
        assert info["name"] == "test_content_embeddings"
        assert "points_count" in info


# ══════════════════════════════════════════════
# QUICK SMOKE TEST — Run without any databases
# ══════════════════════════════════════════════

class TestSmokeTest:
    """
    Fast smoke test that verifies the full data model pipeline
    without any external dependencies. This is what you run first
    to make sure all your models and schemas are correct.
    """

    def test_full_pipeline_data_flow(self):
        """Simulate the complete data flow through models."""

        # 1. Ingestion: create a raw content item
        raw_item = ContentItem(
            source_platform=SourcePlatform.REDDIT,
            source_url="https://reddit.com/r/MachineLearning/comments/test",
            author="ai_researcher",
            title="Breakthrough: New Agent Framework Outperforms AutoGPT",
            content_text="We've developed a new multi-agent framework that achieves 2x performance...",
            published_at=datetime(2026, 3, 15, 9, 0, tzinfo=timezone.utc),
            engagement_score=523,
            raw_metadata={"subreddit": "MachineLearning", "upvote_ratio": 0.95},
        )
        assert raw_item.relevance_score is None  # Not yet analyzed

        # 2. Analysis: simulate Claude Haiku extraction
        extraction = ExtractionResult(
            entities=[
                ExtractedEntity(name="AgentFlow", entity_type=EntityType.FRAMEWORK, confidence=0.92),
                ExtractedEntity(name="AutoGPT", entity_type=EntityType.PRODUCT, confidence=0.88),
            ],
            topics=[
                TopicTag(level1="AI Agents", level2="agent_framework", confidence=0.95),
                TopicTag(level1="Tools & Frameworks", level2="open_source_release", confidence=0.7),
            ],
            sentiment=Sentiment.POSITIVE,
            sentiment_confidence=0.91,
            signal_type=SignalType.TOOL_RELEASE,
            relevance_score=8,
            summary="New multi-agent framework AgentFlow claims 2x performance over AutoGPT.",
        )
        assert extraction.relevance_score == 8

        # 3. Merge analysis results into the content item
        analyzed_item = raw_item.model_copy(
            update={
                "relevance_score": extraction.relevance_score,
                "sentiment": extraction.sentiment,
                "sentiment_confidence": extraction.sentiment_confidence,
                "signal_type": extraction.signal_type,
                "summary": extraction.summary,
                "entities": extraction.entities,
                "topics": extraction.topics,
                "embedding_id": f"vec_{raw_item.id}",
            }
        )
        assert analyzed_item.relevance_score == 8
        assert analyzed_item.sentiment == Sentiment.POSITIVE
        assert len(analyzed_item.entities) == 2
        assert analyzed_item.embedding_id is not None

        # 4. Digest: create a signal from the analyzed item
        signal = DigestSignal(
            rank=3,
            title=analyzed_item.title or "Untitled",
            summary=analyzed_item.summary or "",
            sentiment=analyzed_item.sentiment,
            signal_type=analyzed_item.signal_type,
            source_urls=[analyzed_item.source_url],
            source_platforms=[analyzed_item.source_platform.value],
        )

        digest = Digest(
            period_start=datetime(2026, 3, 14, tzinfo=timezone.utc),
            period_end=datetime(2026, 3, 15, tzinfo=timezone.utc),
            signals=[signal],
            total_items_processed=847,
        )
        assert len(digest.signals) == 1
        assert digest.signals[0].rank == 3

        # 5. Verify full serialization
        full_dict = analyzed_item.model_dump()
        assert full_dict["source_platform"] == "reddit"
        assert full_dict["signal_type"] == "tool_release"
        assert full_dict["entities"][0]["name"] == "AgentFlow"
        assert isinstance(full_dict["published_at"], datetime)

        # If we got here, the entire data model pipeline works
        print("\n✅ Full pipeline data flow test passed!")
        print(f"   Item ID: {analyzed_item.id}")
        print(f"   Platform: {analyzed_item.source_platform}")
        print(f"   Relevance: {analyzed_item.relevance_score}/10")
        print(f"   Signal: {analyzed_item.signal_type}")
        print(f"   Entities: {[e.name for e in analyzed_item.entities]}")
        print(f"   Summary: {analyzed_item.summary}")
