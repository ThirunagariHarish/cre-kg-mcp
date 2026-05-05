# CRE Ontology Knowledge Graph MCP Server

Commercial Real Estate knowledge graph powered by Neo4j + GDS, seeded from
Snowflake, and exposed to Claude Desktop via MCP tools.

**Hackathon Phase 4** — High-level NL tools: `find_matching_properties_for_insight`,
`suggest_next_best_actions_for_deal`, `recommend_broker_for_deal` + demo script.

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

#### macOS config location

```
~/Library/Application Support/Claude/claude_desktop_config.json
```

Copy the snippet from `examples/claude_desktop_config.json` into that file (merge
into any existing `mcpServers` block):

> **Note:** Replace `/Users/harishkumar/.local/bin/uv` with the output of `which uv` on your machine before pasting the block below.

> **Note on Snowflake env vars:** The MCP server is read-only Neo4j by design and does not connect to Snowflake directly. Snowflake env vars (`SNOWFLAKE_*`) are consumed only by the ingester and backfill scripts — they are NOT needed in `claude_desktop_config.json`.

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

**Restart Claude Desktop** (quit completely, then re-open) after editing the
config file. Claude Desktop auto-discovers tools on startup.

After restart you should see **9 tools** available:
`find_matching_properties_for_insight`, `suggest_next_best_actions_for_deal`,
`recommend_broker_for_deal`, `semantic_search`, `traverse_graph`,
`list_communities`, `predict_links`, `health_check`, `cypher_query`.

Ask Claude: **"Run a health check on the CRE graph"**

#### Sample Claude prompts for the 3 canonical questions

**Q1 — Finding matching properties from a market insight:**
```
Based on the latest Dallas Industrial absorption insight, what are the matching
properties and brokers I can reach out to?
```

**Q2 — Next best actions on a stalled deal:**
```
Based on my deal PUR-001 in its current state, what actions can I take?
```

**Q3 — Best broker recommendation:**
```
Who is the best broker to work with me on an Industrial deal in Dallas
for tenant representation?
```

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

---

## Phase 4 — High-Level NL Tools + Demo

Phase 4 adds three intent-named tools that answer the three canonical PRD
questions using graph traversal + ML signal. These tools are auto-discovered by
the MCP server — no server.py edit required.

### Running the end-to-end demo

```bash
bash scripts/demo.sh
```

This script: starts Neo4j, runs backfill if needed, starts the ingester and ML
worker in the background, polls until enrichments are ready (50+ Insights,
embeddings, communities, predicted links), then prints:

```
Ready to demo. Now in Claude Desktop ask: ...
```

### Tool: `find_matching_properties_for_insight` (Q1)

Given a market insight (by ID or free text), surfaces matching properties and
brokers.

```
"Based on the latest Dallas Industrial absorption insight, what are the
matching properties and brokers I can reach out to?"
```

Internally:
1. Resolves the insight via ID or `semantic_search`.
2. Extracts Market + AssetClass from `:ABOUT` edges.
3. Finds properties via `LOCATED_IN` + `CLASSIFIED_AS`.
4. Finds brokers via `COVERS` + `SPECIALIZES_IN` + `BROKERED_BY`.
5. Ranks properties by (asset_class × 0.40 + market × 0.40 + recency × 0.20).

### Tool: `suggest_next_best_actions_for_deal` (Q2)

Given a Pursuit ID, recommends next actions based on similar historical deals.

```
"Based on my deal PUR-001 in its current state, what actions can I take?"
```

Returns: comparable pursuits, the brokers who closed them, suggested actions,
related insights from the same market/asset class, and SPOC contacts.

When no comparables exist, returns a transparent fallback message rather than
fabricating actions.

### Tool: `recommend_broker_for_deal` (Q3)

Recommends brokers for a deal by market + asset class + service line.

```
"Who is the best broker to work with me on an Industrial deal in Dallas
for tenant representation?"
```

Ranking weights (documented in `mcp_server/ranker.py`):
- Deal volume in market: 0.40
- Asset-class specialization: 0.25
- Active SPOC assignment: 0.20
- Community overlap: 0.10
- Predicted affinity score: 0.05

Expired SPOCs are flagged (`spoc_status: "expired"`) and ranked lower — never
silently dropped.

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

Phase 4 added 3 high-level NL tools: `find_matching_properties_for_insight`,
`suggest_next_best_actions_for_deal`, `recommend_broker_for_deal`.

---

## File Structure

```
.
├── .env.example                 # credential template (commit); .env is gitignored
├── docker-compose.yml           # Neo4j 5.15 + GDS
├── pyproject.toml               # uv/hatch Python project
├── Makefile                     # bootstrap / backfill / mcp / test targets
├── examples/
│   └── claude_desktop_config.json  # Claude Desktop MCP config snippet
├── scripts/
│   ├── backfill.py              # convenience entry point for full backfill
│   └── demo.sh                  # end-to-end demo launcher
├── ingester/
│   ├── snowflake_client.py      # Snowflake auth + batched fetch
│   ├── normalizer.py            # merge-key derivation + taxonomy canonicalization
│   ├── canonical_map.yaml       # market / asset-class / service-line aliases
│   ├── graph_writer.py          # Neo4j MERGE templates + schema bootstrap
│   ├── backfill.py              # backfill orchestrator (locked order)
│   ├── streaming.py             # Phase 2: long-running insight ingester (poll+embed)
│   └── embedding.py             # shared sentence-transformers embed helper
├── ml/
│   ├── embeddings.py            # Phase 3: Node2Vec embeddings
│   ├── communities.py           # Phase 3: Louvain community detection
│   ├── link_prediction.py       # Phase 3: link prediction (adamicAdar)
│   └── refresh.py               # Phase 3: scheduled ML refresh worker
├── mcp_server/
│   ├── server.py                # FastMCP stdio server + auto-discovery
│   ├── neo4j_client.py          # read-only driver singleton
│   ├── ranker.py                # Phase 4: shared ranking helpers + weight constants
│   └── tools/
│       ├── health_check.py      # health_check MCP tool
│       ├── cypher_query.py      # cypher_query MCP tool (debug only)
│       ├── semantic_search.py   # Phase 2: semantic_search MCP tool
│       ├── traverse_graph.py    # Phase 3: graph BFS traversal
│       ├── list_communities.py  # Phase 3: Louvain community listing
│       ├── predict_links.py     # Phase 3: link prediction results
│       ├── find_matching_properties_for_insight.py  # Phase 4: Q1 tool
│       ├── suggest_next_best_actions_for_deal.py    # Phase 4: Q2 tool
│       └── recommend_broker_for_deal.py             # Phase 4: Q3 tool
├── sql/
│   └── streams/
│       └── insights_stream.sql  # Snowflake Stream + Task DDL (idempotent)
└── tests/
    ├── test_normalizer.py
    ├── test_snowflake_client.py
    ├── test_health_check.py
    ├── test_cypher_query.py
    ├── test_graph_writer.py
    ├── test_mcp_registration.py
    ├── test_streaming_ingester.py
    ├── test_insight_normalization.py
    ├── test_semantic_search.py
    ├── test_traverse_graph.py
    ├── test_communities.py
    ├── test_link_prediction.py
    ├── test_embeddings.py
    ├── test_refresh_scheduler.py
    ├── test_ranker.py                  # Phase 4: ranking helpers
    ├── test_find_matching.py           # Phase 4: Q1 tool tests
    ├── test_next_best_actions.py       # Phase 4: Q2 tool tests
    └── test_recommend_broker.py        # Phase 4: Q3 tool tests
```
