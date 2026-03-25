# AI Intelligence Engine

Automated signal detection, analysis, and delivery pipeline for AI/ML developments.

Collects content from Reddit, Hacker News, X/Twitter, YouTube, RSS feeds, and more — analyzes it with Claude — and delivers a daily email digest of the top 10 signals shaping AI.

## Quick Start (Phase 1 — Foundation)

### Prerequisites

- **Python 3.12+** — [Download](https://python.org/downloads)
- **uv** (recommended) or pip — [Install uv](https://docs.astral.sh/uv/getting-started/installation/)
- **Git**

### 1. Clone and set up the project

```bash
git init ai-intel-engine
cd ai-intel-engine

# If using uv (recommended — 10x faster than pip):
uv venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\activate    # Windows
uv pip install -e ".[dev]"

# If using pip:
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your actual API keys (see setup guides below)
```

### 3. Set up Supabase (PostgreSQL)

1. Go to [supabase.com](https://supabase.com) → **New Project** (free tier)
2. Choose a region close to you, set a database password
3. Once created, go to **Project Settings → Database**
4. Copy the **Connection string (URI)** — use the "connection pooling" version
5. Paste it into `.env` as `SUPABASE_DB_URL` (change `postgresql://` to `postgresql+asyncpg://`)
6. Go to **SQL Editor** → paste and run `scripts/001_initial_schema.sql`

### 4. Set up Qdrant Cloud (Vector DB)

1. Go to [cloud.qdrant.io](https://cloud.qdrant.io) → **Create Cluster** (free tier)
2. Choose the free tier (1GB), pick a region
3. Once ready, copy the **cluster URL** and **API key**
4. Paste them into `.env` as `QDRANT_URL` and `QDRANT_API_KEY`

### 5. Set up Anthropic API

1. Go to [console.anthropic.com](https://console.anthropic.com) → **API Keys**
2. Create a new key, paste it into `.env` as `ANTHROPIC_API_KEY`

### 6. Validate your setup

```bash
python scripts/validate_setup.py
```

### 7. Run tests

```bash
# Unit tests (no database needed):
pytest tests/test_phase1.py -v

# Integration tests (requires live databases):
pytest tests/test_phase1.py -v -m integration
```

## Project Structure

```
ai-intel-engine/
├── src/
│   ├── config.py              # Settings from .env
│   ├── models.py              # Pydantic data models
│   ├── logging_config.py      # Structured logging
│   ├── storage/
│   │   ├── tables.py          # SQLAlchemy table definitions
│   │   ├── postgres_client.py # PostgreSQL async client
│   │   └── qdrant_client.py   # Qdrant vector DB client
│   ├── ingestion/             # Phase 2: Platform collectors
│   ├── analysis/              # Phase 3: AI analysis pipeline
│   ├── digest/                # Phase 4: Email report generation
│   └── api/                   # Phase 5: Search API
├── config/                    # Source definitions, taxonomy
├── templates/                 # Email HTML templates
├── scripts/
│   ├── 001_initial_schema.sql # Database migration
│   └── validate_setup.py      # Setup validation script
├── tests/
│   └── test_phase1.py         # Phase 1 milestone tests
├── .env.example               # Environment template
├── .gitignore
├── pyproject.toml             # Dependencies & project config
└── README.md
```

## Phase 1 Milestone

When Phase 1 is complete, you should be able to:

- ✅ Create ContentItem, Entity, and Digest objects with full validation
- ✅ Insert content items into PostgreSQL (Supabase) with deduplication
- ✅ Query items by platform, signal type, relevance score, and date range
- ✅ Upsert and retrieve entities with mention counting
- ✅ Store vector embeddings in Qdrant with metadata payloads
- ✅ Search Qdrant with semantic similarity + metadata filters
- ✅ All tests passing

## What's Next

- **Phase 2 (Days 5–9):** Ingestion — Hacker News, Reddit, RSS, YouTube collectors
- **Phase 3 (Days 10–14):** Analysis — Claude extraction, embeddings, clustering
- **Phase 4 (Days 15–18):** Digest — Signal ranking, email generation, Resend
- **Phase 5 (Days 19–21):** Search API + deployment

## Cost

Estimated $16–34/month for the full MVP. See the architecture document for details.
