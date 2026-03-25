"""
AI analysis pipeline using Claude API.

Processes raw content items through Claude Haiku to extract:
- Entities (companies, people, products, frameworks, models)
- Topics (two-level taxonomy)
- Sentiment (positive/negative/neutral/mixed)
- Signal type (product_launch, funding_round, etc.)
- Relevance score (1-10)
- One-sentence summary

Uses Claude Haiku for extraction (fast + cheap: ~$0.001 per item)
and Claude Sonnet for final signal ranking.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone

import anthropic
import structlog

from src.analysis.prompts import (
    EXTRACTION_SYSTEM_PROMPT,
    EXTRACTION_USER_TEMPLATE,
    RANKING_SYSTEM_PROMPT,
    RANKING_USER_TEMPLATE,
)
from src.models import (
    ContentItem,
    ExtractionResult,
    ExtractedEntity,
    EntityType,
    Sentiment,
    SignalType,
    TopicTag,
)
from src.storage.postgres_client import PostgresClient

logger = structlog.get_logger()

# Model configuration
HAIKU_MODEL = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-20250514"


class AnalysisPipeline:
    """
    AI-powered analysis pipeline for content items.

    Processes unanalyzed items from the database through Claude,
    extracts structured data, and updates the database with results.

    Usage:
        pipeline = AnalysisPipeline(api_key, db_client)
        stats = await pipeline.run(batch_size=50)
    """

    def __init__(self, api_key: str, db: PostgresClient):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.db = db
        self.stats = {
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
        }

    async def run(self, batch_size: int = 50) -> dict:
        """
        Process a batch of unanalyzed items from the database.
        Returns stats dict.
        """
        self.stats = {"processed": 0, "succeeded": 0, "failed": 0, "skipped": 0}
        start = time.time()

        # Fetch unprocessed items
        items = await self.db.get_unprocessed_items(limit=batch_size)
        logger.info("analysis.batch_fetched", count=len(items))

        if not items:
            logger.info("analysis.no_items_to_process")
            return self.stats

        # Process each item through Claude (sequentially to respect rate limits)
        for item_row in items:
            self.stats["processed"] += 1
            try:
                result = await asyncio.to_thread(
                    self._extract_signals, item_row
                )

                if result:
                    # Update the database with analysis results
                    await self.db.update_item_analysis(
                        item_id=item_row.id,
                        relevance_score=result.relevance_score,
                        sentiment=result.sentiment.value,
                        sentiment_confidence=result.sentiment_confidence,
                        signal_type=result.signal_type.value,
                        summary=result.summary,
                        entities=[e.model_dump() for e in result.entities],
                        topics=[t.model_dump() for t in result.topics],
                    )
                    self.stats["succeeded"] += 1

                    logger.debug(
                        "analysis.item_processed",
                        item_id=item_row.id,
                        relevance=result.relevance_score,
                        signal_type=result.signal_type.value,
                        entities=len(result.entities),
                    )
                else:
                    self.stats["skipped"] += 1

                # Small delay to respect rate limits
                await asyncio.sleep(0.2)

            except Exception as e:
                self.stats["failed"] += 1
                logger.error(
                    "analysis.item_failed",
                    item_id=item_row.id,
                    error=str(e),
                )
                # Continue with next item
                await asyncio.sleep(1.0)

        elapsed = time.time() - start
        self.stats["duration_seconds"] = round(elapsed, 1)

        logger.info(
            "analysis.batch_complete",
            **self.stats,
        )
        return self.stats

    def _extract_signals(self, item_row) -> ExtractionResult | None:
        """
        Send a single item to Claude Haiku for structured extraction.
        Returns an ExtractionResult or None if parsing fails.
        """
        # Truncate content to avoid hitting token limits
        content_text = item_row.content_text or ""
        if len(content_text) > 4000:
            content_text = content_text[:4000] + "\n\n[...truncated]"

        user_message = EXTRACTION_USER_TEMPLATE.format(
            source_platform=item_row.source_platform,
            title=item_row.title or "(no title)",
            author=item_row.author or "unknown",
            engagement_score=item_row.engagement_score or 0,
            content_text=content_text,
        )

        try:
            response = self.client.messages.create(
                model=HAIKU_MODEL,
                max_tokens=1024,
                system=EXTRACTION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )

            # Parse the response
            raw_text = response.content[0].text.strip()
            return self._parse_extraction_response(raw_text)

        except anthropic.RateLimitError:
            logger.warning("analysis.rate_limited", item_id=item_row.id)
            time.sleep(5)  # Back off on rate limit
            return None
        except Exception as e:
            logger.error(
                "analysis.claude_error",
                item_id=item_row.id,
                error=str(e),
            )
            return None

    def _parse_extraction_response(self, raw_text: str) -> ExtractionResult | None:
        """Parse Claude's JSON response into an ExtractionResult."""
        try:
            # Handle potential markdown code blocks
            text = raw_text
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            data = json.loads(text)

            # Parse entities
            entities = []
            for e in data.get("entities", []):
                try:
                    entity_type = self._map_entity_type(e.get("entity_type", ""))
                    if entity_type:
                        entities.append(ExtractedEntity(
                            name=e["name"],
                            entity_type=entity_type,
                            confidence=float(e.get("confidence", 0.8)),
                        ))
                except (KeyError, ValueError):
                    continue

            # Parse topics
            topics = []
            for t in data.get("topics", []):
                try:
                    topics.append(TopicTag(
                        level1=t["level1"],
                        level2=t["level2"],
                        confidence=float(t.get("confidence", 0.8)),
                    ))
                except (KeyError, ValueError):
                    continue

            # Parse sentiment
            sentiment_str = data.get("sentiment", "neutral").lower()
            sentiment = self._map_sentiment(sentiment_str)

            # Parse signal type
            signal_str = data.get("signal_type", "other").lower()
            signal_type = self._map_signal_type(signal_str)

            return ExtractionResult(
                entities=entities,
                topics=topics,
                sentiment=sentiment,
                sentiment_confidence=float(data.get("sentiment_confidence", 0.5)),
                signal_type=signal_type,
                relevance_score=max(1, min(10, int(data.get("relevance_score", 5)))),
                summary=data.get("summary", "")[:500],
            )

        except json.JSONDecodeError as e:
            logger.warning("analysis.json_parse_error", error=str(e), raw=raw_text[:200])
            return None
        except Exception as e:
            logger.warning("analysis.parse_error", error=str(e))
            return None

    @staticmethod
    def _map_entity_type(raw: str) -> EntityType | None:
        """Map raw entity type string to EntityType enum."""
        mapping = {
            "company": EntityType.COMPANY,
            "person": EntityType.PERSON,
            "product": EntityType.PRODUCT,
            "framework": EntityType.FRAMEWORK,
            "paper": EntityType.PAPER,
            "organization": EntityType.ORGANIZATION,
            "model": EntityType.MODEL,
        }
        return mapping.get(raw.lower())

    @staticmethod
    def _map_sentiment(raw: str) -> Sentiment:
        """Map raw sentiment string to Sentiment enum."""
        mapping = {
            "positive": Sentiment.POSITIVE,
            "negative": Sentiment.NEGATIVE,
            "neutral": Sentiment.NEUTRAL,
            "mixed": Sentiment.MIXED,
        }
        return mapping.get(raw, Sentiment.NEUTRAL)

    @staticmethod
    def _map_signal_type(raw: str) -> SignalType:
        """Map raw signal type string to SignalType enum."""
        mapping = {
            "product_launch": SignalType.PRODUCT_LAUNCH,
            "funding_round": SignalType.FUNDING_ROUND,
            "research_breakthrough": SignalType.RESEARCH_BREAKTHROUGH,
            "tool_release": SignalType.TOOL_RELEASE,
            "trend_shift": SignalType.TREND_SHIFT,
            "opinion_analysis": SignalType.OPINION_ANALYSIS,
            "tutorial": SignalType.TUTORIAL,
            "hiring_signal": SignalType.HIRING_SIGNAL,
            "partnership": SignalType.PARTNERSHIP,
            "regulatory": SignalType.REGULATORY,
            "acquisition": SignalType.ACQUISITION,
            "open_source": SignalType.OPEN_SOURCE,
            "benchmark": SignalType.BENCHMARK,
            "other": SignalType.OTHER,
        }
        return mapping.get(raw, SignalType.OTHER)