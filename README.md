# CRE Ontology Knowledge Graph MCP Server

Commercial Real Estate knowledge graph powered by Neo4j + GDS, seeded from
Snowflake, and exposed to Claude Desktop via MCP tools.

**Hackathon Phase 2** — Streaming insight pipeline + `Insight` nodes with body embeddings + `semantic_search` MCP tool.

---

## Quick Start (under 10 minutes)

### Prerequisites

- macOS with Docker Desktop running
- Python 3.11+
- `uv` installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Claude Desktop (for the MCP integration)

### 1. Clone and configure

```bash
git clone <repo-url>
cd Projects

# Copy the env template and fill in your credentials
cp .env.example .env
# Edit .env with your Snowflake credentials and Neo4j password
```

### 2. Bootstrap (Neo4j + Python deps)

```bash
make bootstrap
```

This:
- Installs all Python dependencies via `uv sync`
- Starts Neo4j 5.15 Community with GDS plugin via Docker Compose
- Waits up to 3 minutes for `CALL gds.version()` to succeed

Verify Neo4j is healthy:
```bash
docker compose ps
# neo4j should show "healthy"
```

### 3. Run the backfill

```bash
make backfill
# or: python scripts/backfill.py
```

Loads all 5 Snowflake tables in locked order:
`CRE_BROKERS → CRE_PROPERTIES → CRE_LEASE_COMPS → CRE_PURSUITS → CRE_SPOC`

Check node counts in Neo4j Browser at http://localhost:7474
(login: neo4j / your NEO4J_PASSWORD from .env):

```cypher
MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt ORDER BY cnt DESC
```

### 4. Connect Claude Desktop

Add this to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cre-kg": {
      "command": "/Users/harishkumar/.local/bin/uv",
      "args": [
        "run",
        "--project",
        "/Users/harishkumar/Projects",
        "python",
        "-m",
        "mcp_server.server"
      ],
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "hackathon_local_only"
      }
    }
  }
}
```

Restart Claude Desktop. You should see 3 tools available:
`semantic_search`, `health_check`, and `cypher_query`.

Ask Claude: **"Run a health check on the CRE graph"**

---

## Phase 2 — Streaming Insight Pipeline

### Running the streaming ingester

The ingester is a long-lived process that:
1. Backfills all existing rows from `CRE_MARKET_INSIGHTS` into Neo4j (50 seeded rows).
2. Polls `CRE_INSIGHTS_DELTA` every 60s for new rows written by the Snowflake Task.
3. Upserts each insight as an `:Insight` node with a 384-dim body embedding (all-MiniLM-L6-v2).
4. Creates `:ABOUT` edges to Market, Submarket, AssetClass, and Tenant nodes.

```bash
# Start the ingester (long-running, run in a separate terminal or via docker compose)
uv run python -m ingester.streaming

# Or via the console script
cre-ingest
```

Environment variable `INGEST_POLL_SECONDS` controls the polling interval (default: 60).

### Deploying the Snowflake Stream + Task

Run `sql/streams/insights_stream.sql` once in a Snowflake worksheet or via:

```bash
# Applied automatically during Phase 2 setup — re-running is safe (idempotent)
# To apply manually:
snowsql -f sql/streams/insights_stream.sql
```

This creates:
- `CRE_INSIGHTS_STREAM` — append-only stream on `CRE_MARKET_INSIGHTS`
- `CRE_INSIGHTS_DELTA` — staging table the ingester polls
- `CRE_INSIGHTS_TASK` — 1-minute scheduled task moving stream rows to delta

Verify the Task is running:
```sql
SHOW TASKS LIKE 'CRE_INSIGHTS_TASK' IN SCHEMA HACKATHON.PUBLIC;
-- State column should show 'started'
```

### Using `semantic_search` from Claude

Ask Claude any of:

```
"Find the latest insight about industrial absorption"
"What insights relate to sublease pressure?"
"Find insights about tenant downsizing in Atlanta"
"semantic_search label=Insight query_text='office leasing demand'"
```

Filters available: `market`, `asset_class`, `date_from`, `date_to`.

Example tool call:
```json
{
  "label": "Insight",
  "query_text": "tenant downsizing sublease pressure",
  "top_k": 5,
  "market": "Atlanta"
}
```

### Verifying the ingest

After starting the ingester, check Neo4j:
```cypher
MATCH (i:Insight) RETURN count(i) AS total_insights;
// Expected: 50

MATCH (i:Insight)-[:ABOUT]->(n) RETURN labels(n)[0] AS target, count(*) AS edges
ORDER BY edges DESC;
// Expected: Market 50, Submarket 50, AssetClass 50, Tenant ~6

MATCH (i:Insight) WHERE i.embedding IS NOT NULL RETURN count(i) AS with_embeddings;
// Expected: 50
```

---

## Running Tests

```bash
# Unit tests only (no Docker required)
make test

# Integration tests (requires Docker + Neo4j running)
make test-integration
```

---

## Rollback

```bash
# Stop containers (keeps data)
make down

# Stop and destroy Neo4j data volume (clean slate)
make down-v
```

Snowflake is read-only in Phase 1 — no rollback needed there.

---

## Architecture

```
Claude Desktop
    │  stdio MCP
    ▼
mcp_server/server.py          ← tools: semantic_search, health_check, cypher_query
    │  Bolt 7687
    ▼
Neo4j 5.15 + GDS              ← Docker Compose, local volume
    ▲                ▲
ingester/backfill.py          ingester/streaming.py  ← long-running ingester
    │                              │ polls every 60s
Snowflake HACKATHON.PUBLIC ←── CRE_INSIGHTS_DELTA ←── CRE_INSIGHTS_STREAM (Task 1min)
    (read-only, ACCOUNTADMIN)      (staging table)       (on CRE_MARKET_INSIGHTS)
```

Phase 3 will add `ingester/ml_enricher.py` + GDS Node2Vec / Louvain / link prediction.
Phase 4 will add 3 high-level tools: `find_matching_properties_for_insight`,
`suggest_next_best_actions_for_deal`, `recommend_broker_for_deal`.

---

## File Structure

```
.
├── .env.example                 # credential template (commit); .env is gitignored
├── docker-compose.yml           # Neo4j 5.15 + GDS
├── pyproject.toml               # uv/hatch Python project
├── Makefile                     # bootstrap / backfill / mcp / test targets
├── ingester/
│   ├── snowflake_client.py      # Snowflake auth + batched fetch
│   ├── normalizer.py            # merge-key derivation + taxonomy canonicalization
│   ├── canonical_map.yaml       # market / asset-class / service-line aliases
│   ├── graph_writer.py          # Neo4j MERGE templates + schema bootstrap
│   ├── backfill.py              # backfill orchestrator (locked order)
│   └── streaming.py             # Phase 2: long-running insight ingester (poll+embed)
├── mcp_server/
│   ├── server.py                # FastMCP stdio server + tool registry
│   ├── neo4j_client.py          # read-only driver singleton
│   └── tools/
│       ├── health_check.py      # health_check MCP tool (+ freshness reporting)
│       ├── cypher_query.py      # cypher_query MCP tool (debug only)
│       └── semantic_search.py   # Phase 2: semantic_search MCP tool
├── sql/
│   └── streams/
│       └── insights_stream.sql  # Phase 2: Snowflake Stream + Task DDL (idempotent)
├── scripts/
│   └── backfill.py              # convenience entry point
└── tests/
    ├── test_normalizer.py            # pure unit tests for merge keys + taxonomy
    ├── test_snowflake_client.py      # mocked Snowflake connection tests
    ├── test_health_check.py          # mocked Neo4j driver tests
    ├── test_cypher_query.py          # read-only enforcement tests
    ├── test_graph_writer.py          # testcontainers integration tests
    ├── test_mcp_registration.py      # tool registration smoke tests
    ├── test_streaming_ingester.py    # Phase 2: mocked Snowflake + Neo4j upsert tests
    ├── test_insight_normalization.py # Phase 2: unmapped taxonomy pass-through tests
    └── test_semantic_search.py       # Phase 2: mocked embedding ranking tests
```
