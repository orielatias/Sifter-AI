"""
Ingestion layer — platform-specific content collectors.
"""

from src.ingestion.base import BaseCollector
from src.ingestion.hackernews import HackerNewsCollector
from src.ingestion.orchestrator import IngestionOrchestrator

__all__ = [
    "BaseCollector",
    "HackerNewsCollector",
    "IngestionOrchestrator",
]
