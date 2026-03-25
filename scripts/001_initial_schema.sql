-- ============================================
-- AI Intelligence Engine — Database Migration
-- ============================================
-- Run this against your Supabase PostgreSQL instance.
-- Supabase SQL Editor: https://supabase.com → SQL Editor → New Query
--
-- This creates all tables and indexes defined in the architecture doc.
-- Safe to run multiple times (uses IF NOT EXISTS).

-- ── Enable UUID extension ──
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ══════════════════════════════════════════════
-- TABLE: content_items
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS content_items (
    id              VARCHAR(36) PRIMARY KEY,
    source_platform VARCHAR(50)  NOT NULL,
    source_url      TEXT         NOT NULL,
    author          VARCHAR(255) DEFAULT '',
    title           TEXT,
    content_text    TEXT         NOT NULL,

    -- Timestamps
    published_at    TIMESTAMPTZ  NOT NULL,
    collected_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    -- Engagement
    engagement_score INTEGER     DEFAULT 0,

    -- AI-generated fields (populated by analysis pipeline)
    relevance_score  SMALLINT,
    sentiment        VARCHAR(20),
    sentiment_confidence FLOAT,
    signal_type      VARCHAR(50),
    summary          TEXT,
    entities         JSONB,
    topics           JSONB,
    raw_metadata     JSONB,

    -- Storage references
    embedding_id     VARCHAR(100),
    cluster_id       INTEGER,
    is_top_signal    BOOLEAN      DEFAULT FALSE,

    -- Row metadata
    created_at       TIMESTAMPTZ  DEFAULT NOW(),

    -- Constraints
    CONSTRAINT uq_content_items_source_url UNIQUE (source_url)
);

-- Indexes for content_items
CREATE INDEX IF NOT EXISTS ix_content_items_collected_at
    ON content_items (collected_at DESC);

CREATE INDEX IF NOT EXISTS ix_content_items_platform_collected
    ON content_items (source_platform, collected_at DESC);

CREATE INDEX IF NOT EXISTS ix_content_items_relevance
    ON content_items (relevance_score DESC, collected_at DESC);

CREATE INDEX IF NOT EXISTS ix_content_items_signal_type
    ON content_items (signal_type, collected_at DESC);

CREATE INDEX IF NOT EXISTS ix_content_items_is_top_signal
    ON content_items (is_top_signal)
    WHERE is_top_signal = TRUE;

-- GIN index for JSONB entity queries (e.g., find items mentioning "Anthropic")
CREATE INDEX IF NOT EXISTS ix_content_items_entities_gin
    ON content_items USING GIN (entities);


-- ══════════════════════════════════════════════
-- TABLE: entities
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS entities (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL UNIQUE,
    entity_type     VARCHAR(50)  NOT NULL,
    first_seen_at   TIMESTAMPTZ  DEFAULT NOW(),
    mention_count   INTEGER      DEFAULT 1,
    metadata        JSONB
);

CREATE INDEX IF NOT EXISTS ix_entities_type
    ON entities (entity_type);

CREATE INDEX IF NOT EXISTS ix_entities_mention_count
    ON entities (mention_count DESC);


-- ══════════════════════════════════════════════
-- TABLE: digests
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS digests (
    id                   SERIAL PRIMARY KEY,
    period_start         TIMESTAMPTZ  NOT NULL,
    period_end           TIMESTAMPTZ  NOT NULL,
    signal_ids           VARCHAR(36)[],
    total_items_processed INTEGER     DEFAULT 0,
    report_html          TEXT,
    sent_at              TIMESTAMPTZ,
    recipient_count      INTEGER      DEFAULT 0,
    created_at           TIMESTAMPTZ  DEFAULT NOW()
);


-- ══════════════════════════════════════════════
-- TABLE: dead_letter_queue (for failed items)
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS dead_letter_queue (
    id              SERIAL PRIMARY KEY,
    source_platform VARCHAR(50),
    source_url      TEXT,
    error_message   TEXT,
    raw_payload     JSONB,
    retry_count     INTEGER      DEFAULT 0,
    created_at      TIMESTAMPTZ  DEFAULT NOW(),
    last_retry_at   TIMESTAMPTZ
);


-- ══════════════════════════════════════════════
-- Verification: list all tables
-- ══════════════════════════════════════════════
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
ORDER BY table_name;
