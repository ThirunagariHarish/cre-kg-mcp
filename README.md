# CRE Ontology Knowledge Graph MCP Server

Commercial Real Estate knowledge graph powered by Neo4j + GDS, seeded from
Snowflake, and exposed to Claude Desktop via MCP tools.

**Hackathon Phase 1** — Snowflake backfill + `health_check` + `cypher_query`.

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

Restart Claude Desktop. You should see 2 tools available:
`health_check` and `cypher_query`.

Ask Claude: **"Run a health check on the CRE graph"**

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
mcp_server/server.py          ← registered tools: health_check, cypher_query
    │  Bolt 7687
    ▼
Neo4j 5.15 + GDS              ← Docker Compose, local volume
    ▲
ingester/backfill.py          ← one-shot: Snowflake → Neo4j
    │
Snowflake HACKATHON.PUBLIC    ← read-only (ACCOUNTADMIN role)
```

Phase 2 will add `ingester/insight_consumer.py` + streaming ingester.
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
│   └── backfill.py              # backfill orchestrator (locked order)
├── mcp_server/
│   ├── server.py                # FastMCP stdio server + tool registry
│   ├── neo4j_client.py          # read-only driver singleton
│   └── tools/
│       ├── health_check.py      # health_check MCP tool
│       └── cypher_query.py      # cypher_query MCP tool (debug only)
├── scripts/
│   └── backfill.py              # convenience entry point
└── tests/
    ├── test_normalizer.py       # pure unit tests for merge keys + taxonomy
    ├── test_snowflake_client.py # mocked Snowflake connection tests
    ├── test_health_check.py     # mocked Neo4j driver tests
    ├── test_cypher_query.py     # read-only enforcement tests
    ├── test_graph_writer.py     # testcontainers integration tests
    └── test_mcp_registration.py # tool registration smoke tests
```
