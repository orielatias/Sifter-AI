"""
Centralized configuration loaded from environment variables.
Uses pydantic-settings for validation and type coercion.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ──
    supabase_db_url: str
    supabase_db_url_direct: str = ""  # For migrations only

    # ── Qdrant ──
    qdrant_url: str
    qdrant_api_key: str
    qdrant_collection: str = "content_embeddings"
    embedding_dimension: int = 1024  # Voyage AI voyage-3-lite

    # ── Anthropic ──
    anthropic_api_key: str

    # ── Voyage AI ──
    voyage_api_key: str = ""

    # ── Resend ──
    resend_api_key: str = ""
    digest_from_email: str = "digest@yourdomain.com"
    digest_to_emails: str = ""  # Comma-separated

    # ── Reddit ──
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "ai-intel-engine/0.1"

    # ── YouTube ──
    youtube_api_key: str = ""

    # ── App ──
    log_level: str = "INFO"
    environment: str = "development"
    digest_schedule: str = "daily"
    top_signals_count: int = 10
    min_relevance_score: int = 7

    @property
    def digest_recipients(self) -> list[str]:
        if not self.digest_to_emails:
            return []
        return [e.strip() for e in self.digest_to_emails.split(",") if e.strip()]


def get_settings() -> Settings:
    """Factory function — call this rather than instantiating directly."""
    return Settings()
