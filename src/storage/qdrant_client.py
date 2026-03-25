"""
Qdrant vector database client for semantic search.

Handles embedding storage, similarity search, and filtered retrieval.
Uses the official qdrant-client SDK with async support.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from qdrant_client import QdrantClient, models
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    Range,
    VectorParams,
)

logger = structlog.get_logger()


class QdrantVectorClient:
    """
    Vector database client for the AI Intelligence Engine.
    
    Manages the content_embeddings collection in Qdrant Cloud.
    Supports upsert, semantic search, and filtered queries.
    
    Usage:
        client = QdrantVectorClient(url, api_key, dimension=1024)
        await client.initialize()
        await client.upsert_embedding(item_id, vector, payload)
        results = await client.search("AI agent frameworks", top_k=10)
        await client.close()
    """

    def __init__(
        self,
        url: str,
        api_key: str,
        collection_name: str = "content_embeddings",
        dimension: int = 1024,
    ):
        self.collection_name = collection_name
        self.dimension = dimension
        # Qdrant Python client supports both sync and async; we use sync
        # internally since Qdrant Cloud calls are I/O-bound and fast.
        self.client = QdrantClient(
            url=url,
            api_key=api_key,
            timeout=30,
        )

    def initialize(self) -> None:
        """
        Create the collection if it doesn't exist.
        Sets up vector config and payload indexes for filtered search.
        """
        collections = self.client.get_collections().collections
        exists = any(c.name == self.collection_name for c in collections)

        if not exists:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.dimension,
                    distance=Distance.COSINE,
                ),
            )
            logger.info(
                "qdrant.collection_created",
                name=self.collection_name,
                dimension=self.dimension,
            )

            # Create payload indexes for filtered search
            for field, schema in [
                ("source_platform", PayloadSchemaType.KEYWORD),
                ("signal_type", PayloadSchemaType.KEYWORD),
                ("sentiment", PayloadSchemaType.KEYWORD),
                ("relevance_score", PayloadSchemaType.INTEGER),
            ]:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field,
                    field_schema=schema,
                )
            logger.info("qdrant.indexes_created")
        else:
            logger.info("qdrant.collection_exists", name=self.collection_name)

    def close(self) -> None:
        """Close the Qdrant client connection."""
        self.client.close()
        logger.info("qdrant.closed")

    # ── Upsert ─────────────────────────────────────────────────────

    def upsert_embedding(
        self,
        point_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> None:
        """
        Insert or update a single embedding with its metadata payload.
        
        Args:
            point_id: Unique ID (typically the content_item.id UUID).
            vector: The embedding vector.
            payload: Metadata for filtered search (platform, signal_type, etc.).
        """
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            ],
        )
        logger.debug("qdrant.point_upserted", point_id=point_id)

    def upsert_embeddings_batch(
        self,
        points: list[dict],
    ) -> None:
        """
        Batch upsert embeddings. Each dict should have: id, vector, payload.
        Processes in chunks of 100 for reliability.
        """
        chunk_size = 100
        total = len(points)

        for i in range(0, total, chunk_size):
            chunk = points[i : i + chunk_size]
            point_structs = [
                PointStruct(
                    id=p["id"],
                    vector=p["vector"],
                    payload=p["payload"],
                )
                for p in chunk
            ]
            self.client.upsert(
                collection_name=self.collection_name,
                points=point_structs,
            )
            logger.info(
                "qdrant.batch_upserted",
                chunk=f"{i + 1}-{min(i + chunk_size, total)}",
                total=total,
            )

    # ── Search ─────────────────────────────────────────────────────

    def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        platform: str | None = None,
        signal_type: str | None = None,
        sentiment: str | None = None,
        min_relevance: int | None = None,
    ) -> list[dict]:
        """
        Semantic search with optional metadata filters.
        
        Returns a list of dicts with: id, score, and payload fields.
        """
        # Build filter conditions
        conditions = []
        if platform:
            conditions.append(
                FieldCondition(field_name="source_platform", match=MatchValue(value=platform))
            )
        if signal_type:
            conditions.append(
                FieldCondition(field_name="signal_type", match=MatchValue(value=signal_type))
            )
        if sentiment:
            conditions.append(
                FieldCondition(field_name="sentiment", match=MatchValue(value=sentiment))
            )
        if min_relevance is not None:
            conditions.append(
                FieldCondition(
                    field_name="relevance_score",
                    range=Range(gte=min_relevance),
                )
            )

        search_filter = Filter(must=conditions) if conditions else None

        results = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=search_filter,
            limit=top_k,
            with_payload=True,
        )

        return [
            {
                "id": str(hit.id),
                "score": hit.score,
                **hit.payload,
            }
            for hit in results.points
        ]

    def get_collection_info(self) -> dict:
        """Get collection stats (point count, config, etc.)."""
        info = self.client.get_collection(self.collection_name)
        return {
            "name": self.collection_name,
            "points_count": info.points_count,
            "status": info.status.value,
        }
