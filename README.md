# CRE Ontology Knowledge Graph MCP Server

Commercial Real Estate knowledge graph powered by Neo4j + GDS, seeded from
Snowflake, and exposed to Claude Desktop via MCP tools.

**Hackathon Phase 3** — ML enrichment: Node2Vec embeddings, Louvain community detection, link prediction + `traverse_graph`, `list_communities`, `predict_links` MCP tools.

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

## Phase 3 — ML Enrichment

Phase 3 adds graph ML enrichment via Neo4j GDS: Node2Vec embeddings (128-dim), Louvain community detection, and link prediction. Three new MCP tools expose the results to Claude.

### Running the ML refresh worker (long-lived)

```bash
# Start the ML refresh worker — runs embeddings → communities → link prediction immediately,
# then on a 10-minute cadence (or immediately if ≥50 new insights since last run).
python -m ml.refresh
```

Expected runtime on seeded data:
- Node2Vec embeddings: ~2 minutes (80 walk length, 128 dims, all entity nodes)
- Louvain communities: ~5-10 seconds
- Link prediction (adamicAdar): ~10-30 seconds

### Running individual ML steps

```bash
# Node2Vec embeddings only — writes 'node2vec_embedding' to all projected nodes
python -m ml.embeddings

# Louvain communities only — writes 'community_id' to all projected nodes
python -m ml.communities

# Link prediction only — writes :PredictedLink nodes
python -m ml.link_prediction
```

### Verifying ML enrichment in Neo4j

```cypher
-- Embeddings: verify node2vec_embedding property exists on Broker nodes
MATCH (n:Broker) WHERE n.node2vec_embedding IS NOT NULL RETURN count(n);
-- Expected: > 0 after ml.embeddings runs

-- Communities: verify community_id written
MATCH (n:Broker) WHERE n.community_id IS NOT NULL RETURN count(n);
MATCH (n:Property) WHERE n.community_id IS NOT NULL RETURN count(n);

-- Top communities by size
MATCH (n) WHERE n.community_id IS NOT NULL
WITH n.community_id AS cid, count(n) AS sz ORDER BY sz DESC LIMIT 5
RETURN cid, sz;

-- Link prediction: count PredictedLink nodes
MATCH (pl:PredictedLink) RETURN count(pl) AS total;
-- Expected: > 10

-- Last ML run time
MATCH (m:MLRunMeta {key: 'global'}) RETURN m.last_run_at;
```

### New MCP tools (Phase 3)

These tools are auto-discovered by the MCP server — no registration change needed.

#### `list_communities`

Ask Claude: **"List the top 5 graph communities and their dominant markets"**

```json
{
  "min_size": 5,
  "limit": 10,
  "include_members_sample": true
}
```

Returns communities with `community_id`, `size`, and sample members (id/label/name).
Returns `DEGRADED` if Louvain has not yet run.

#### `predict_links`

Ask Claude: **"Show predicted broker-property affinities"**

```json
{
  "to_label": "Property",
  "from_node_id": "email::jane@cbre.com",
  "min_score": 0.5,
  "k": 10
}
```

Reads from `:PredictedLink` nodes written by `ml.link_prediction`.
Returns `DEGRADED` if link prediction has not yet run.

#### `traverse_graph`

Ask Claude: **"Show all tenants connected to this landlord's portfolio"**

```json
{
  "start_node_id": "email::jane@cbre.com",
  "start_label": "Broker",
  "max_hops": 2,
  "relationship_types": ["BROKERED_BY", "ON"],
  "node_cap": 100
}
```

BFS traversal capped at **200 nodes / 500 edges** (Atlas locked). Returns `truncated: true`
when cap is hit; prunes by BFS order so closest-to-start nodes are kept.
Max 3 hops enforced regardless of `max_hops` parameter.

### Note on embedding dimensions (M-P2-1)

Phase 2 Insight nodes have 384-dim embeddings from `sentence-transformers/all-MiniLM-L6-v2`
stored as `embedding`. Phase 3 graph-structural nodes (Broker, Property, Tenant, etc.) have
128-dim Node2Vec embeddings stored as `node2vec_embedding`. These are separate properties
to avoid collision. `semantic_search` with `anchor_node_id` works for Broker/Property/Tenant
(reads `embedding` if present, else `node2vec_embedding`). Text-query similarity for
non-Insight labels remains DEGRADED until Phase 4 unification.

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
