"""
Base collector class for all platform-specific ingestion collectors.

Defines the shared interface and utility methods. Every collector
inherits from this and implements the `collect()` method.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import structlog

from src.models import ContentItem

logger = structlog.get_logger()


class BaseCollector(ABC):
    """
    Abstract base class for content collectors.
    
    Each platform collector implements `collect()` which returns
    a list of normalized ContentItem objects ready for storage.
    """

    platform_name: str = "unknown"

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.stats = {
            "collected": 0,
            "filtered": 0,
            "errors": 0,
        }

    @abstractmethod
    async def collect(self) -> list[ContentItem]:
        """
        Collect content from the platform and return normalized items.
        Must be implemented by each platform-specific collector.
        """
        ...

    def _reset_stats(self) -> None:
        self.stats = {"collected": 0, "filtered": 0, "errors": 0}

    def _passes_engagement_filter(self, score: int) -> bool:
        """Check if an item meets the minimum engagement threshold."""
        min_engagement = self.config.get("min_engagement", 0)
        return score >= min_engagement

    def _passes_content_filter(self, text: str) -> bool:
        """Check if content meets minimum length requirements."""
        if not text or len(text.strip()) < 50:
            return False
        if len(text) > 50_000:
            return False
        return True

    def _has_ai_keywords(self, text: str) -> bool:
        """Quick keyword check to filter for AI-relevant content."""
        keywords = {
            "ai", "artificial intelligence", "machine learning", "deep learning",
            "llm", "large language model", "gpt", "claude", "gemini", "mistral",
            "transformer", "neural network", "nlp", "computer vision",
            "reinforcement learning", "fine-tuning", "fine tuning", "rag",
            "retrieval augmented", "vector database", "embedding",
            "agent", "agentic", "multi-agent", "autonomous agent",
            "mcp", "model context protocol", "tool use", "function calling",
            "openai", "anthropic", "google deepmind", "meta ai", "hugging face",
            "stable diffusion", "midjourney", "dall-e", "sora",
            "startup", "funding", "series a", "series b", "venture capital",
            "vc", "yc", "y combinator", "techstars",
            "open source", "github", "benchmark", "sota", "state of the art",
            "diffusion model", "generative ai", "gen ai", "copilot",
            "langchain", "llamaindex", "crewai", "autogen", "semantic kernel",
        }
        text_lower = text.lower()
        return any(kw in text_lower for kw in keywords)

    def log_collection_complete(self) -> None:
        logger.info(
            f"collector.{self.platform_name}.complete",
            collected=self.stats["collected"],
            filtered=self.stats["filtered"],
            errors=self.stats["errors"],
        )
