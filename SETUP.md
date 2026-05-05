# Setup Guide — CRE Knowledge Graph MCP Server

This guide gets a new user from zero to a working demo in ~15 minutes on macOS or Linux.

What you'll end up with: an MCP server attached to Claude Desktop that can answer CRE questions grounded in a Neo4j knowledge graph, fed by Snowflake CRE data + streaming market-research insights, enriched with Node2Vec embeddings, Louvain communities, and Adamic-Adar link prediction.

---

## 0. Prerequisites

| Tool | Why | Install |
|---|---|---|
| **macOS or Linux** | Tested on macOS (Darwin 25.x); Linux should work | — |
| **Docker Desktop** | Runs Neo4j + GDS plugin locally | https://www.docker.com/products/docker-desktop/ |
| **`uv` (Python package manager)** | Fast Python deps, used to launch the MCP server | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **`git`** | Clone the repo | Already on macOS; on Linux: `apt install git` |
| **Claude Desktop** | The MCP host | https://claude.ai/download |
| **A Snowflake account** | Source data | Either reuse the demo HACKATHON.PUBLIC schema or your own |

Verify:

```bash
docker --version            # 24.x or newer
uv --version                # 0.4.x or newer
git --version               # any modern version
which uv                    # ⚠️ note this path — you'll paste it into Claude config later
```

---

## 1. Clone the repo

```bash
git clone https://github.com/<owner>/cre-kg-mcp.git
cd cre-kg-mcp
```

(Replace `<owner>` with the GitHub org/user where this repo lives.)

---

## 2. Configure environment

Copy the example env file and fill in your secrets:

```bash
cp .env.example .env
```

Edit `.env`:

```bash
# Snowflake — required if you want to ingest from a Snowflake source
SNOWFLAKE_ACCOUNT=<your-account>      # e.g. RODBNOV-HL98478
SNOWFLAKE_USER=<your-user>            # service account recommended
SNOWFLAKE_PASSWORD=<your-password>    # do NOT commit
SNOWFLAKE_ROLE=ACCOUNTADMIN
SNOWFLAKE_WAREHOUSE=COMPUTE_WH
SNOWFLAKE_DATABASE=HACKATHON
SNOWFLAKE_SCHEMA=PUBLIC

# Neo4j — defaults match docker-compose.yml; change if you point at Neo4j Aura
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=hackathon_local_only

# Ingester poll interval (seconds)
INGEST_POLL_SECONDS=60
```

**Important:** `.env` is in `.gitignore`. Never commit it.

If you don't have Snowflake access, see "Mock-only setup" at the bottom.

---

## 3. Start Neo4j + GDS

```bash
docker compose up -d
```

Wait ~30 seconds, then verify GDS is loaded:

```bash
docker compose exec -T neo4j cypher-shell -u neo4j -p "$(grep NEO4J_PASSWORD .env | cut -d= -f2)" \
  "CALL gds.version() YIELD gdsVersion RETURN gdsVersion"
```

You should see `2.6.x` returned.

Neo4j Browser is now at http://localhost:7474 (login `neo4j` / your password).

---

## 4. Install Python deps

```bash
uv sync
```

This creates `.venv/` and installs every dep pinned in `uv.lock` (~3 min on first run because of `torch` + `sentence-transformers`).

---

## 5. Seed the source data (Snowflake)

If you're using the demo HACKATHON.PUBLIC schema, the 5 base CRE tables are already there. You also need a `CRE_MARKET_INSIGHTS` table — seed it with the included script:

```bash
uv run python scripts/seed_insights.py
```

This creates `HACKATHON.PUBLIC.CRE_MARKET_INSIGHTS` and inserts 50 synthetic insights spanning 10 markets, mixed asset classes, with 6 tenant-specific rows for entity-resolution against `CRE_LEASE_COMPS.TENANT_NAME`.

Skip this step if your schema already has the 5 CRE tables and an insight table you want to use instead — adjust column names in `ingester/streaming.py` if they differ.

---

## 6. Backfill the graph

```bash
uv run python scripts/backfill.py
```

Loads all 5 source tables (`CRE_BROKERS`, `CRE_PROPERTIES`, `CRE_LEASE_COMPS`, `CRE_PURSUITS`, `CRE_SPOC`) into Neo4j as a CRE-domain ontology. Takes ~2–3 min.

Verify:

```bash
docker compose exec -T neo4j cypher-shell -u neo4j -p "$(grep NEO4J_PASSWORD .env | cut -d= -f2)" \
  "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS c ORDER BY c DESC"
```

Expected: ~8K Brokers, ~20K Properties, ~10K Leases, ~10K Pursuits, plus Markets/Submarkets/AssetClasses.

---

## 7. Start the long-lived background services

These two processes keep the graph fresh:

```bash
# Terminal 1 — streaming ingester (polls Snowflake every 60s for new insights)
uv run python -m ingester.streaming

# Terminal 2 — ML refresh (Node2Vec + Louvain + link prediction every 10 min)
uv run python -m ml.refresh
```

Or run them detached if you prefer:

```bash
nohup uv run python -m ingester.streaming > /tmp/cre_ingester.log 2>&1 &
nohup uv run python -m ml.refresh         > /tmp/cre_ml.log 2>&1 &
```

The first ML refresh runs immediately (takes ~30s on the seeded data), then every 10 min.

After ~30s, verify:

```bash
docker compose exec -T neo4j cypher-shell -u neo4j -p "$(grep NEO4J_PASSWORD .env | cut -d= -f2)" \
  "MATCH (b:Broker) WHERE b.embedding IS NOT NULL RETURN count(b) AS embedded"
```

Should be > 0.

---

## 8. Wire the MCP server into Claude Desktop

The MCP server itself is launched on-demand by Claude Desktop. You don't run it manually — you just tell Claude Desktop how to launch it.

### macOS

```bash
mkdir -p "$HOME/Library/Application Support/Claude"
```

Open `~/Library/Application Support/Claude/claude_desktop_config.json` (create it if it doesn't exist).

If the file is empty, paste this (replacing the two placeholders):

```json
{
  "mcpServers": {
    "cre-kg": {
      "command": "<output of: which uv>",
      "args": [
        "run",
        "--project",
        "<absolute path to your cloned cre-kg-mcp directory>",
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

If the file already exists with other MCP servers, **merge** by adding the `cre-kg` entry inside `mcpServers`. Don't overwrite — you'll lose your existing servers.

Concrete example with real paths filled in:

```json
{
  "mcpServers": {
    "cre-kg": {
      "command": "/Users/yourname/.local/bin/uv",
      "args": ["run", "--project", "/Users/yourname/code/cre-kg-mcp", "python", "-m", "mcp_server.server"],
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "hackathon_local_only"
      }
    }
  }
}
```

### Linux

Same JSON but at `~/.config/Claude/claude_desktop_config.json`.

### Windows

Same JSON but at `%APPDATA%\Claude\claude_desktop_config.json`. Use Windows-style paths.

---

## 9. Restart Claude Desktop

Fully quit and relaunch Claude Desktop (CMD+Q on macOS — not just close the window).

When it relaunches, the tools indicator (🔧) should show **9 cre-kg tools**:

- `health_check`
- `cypher_query`
- `semantic_search`
- `find_matching_properties_for_insight`
- `suggest_next_best_actions_for_deal`
- `recommend_broker_for_deal`
- `traverse_graph`
- `list_communities`
- `predict_links`

---

## 10. Try the demo prompts

In a new Claude Desktop conversation, ask:

> Run health_check.

Claude should call `health_check` and return `{snowflake_probe: not_probed_by_mcp_process, neo4j: ok, gds: 2.6.x, last_ml_run_at: <recent ISO>, ml_freshness_warning: false, ...}`.

Then try the 3 canonical questions:

1. **"Based on the Microsoft Boston insight INS-20260319-001, what are the matching properties and brokers I can reach out to?"** — exercises `find_matching_properties_for_insight`.

2. **"Based on my pursuit PUR-0000001, what next best actions can I take?"** — exercises `suggest_next_best_actions_for_deal`.

3. **"Who is the best broker to work with me on a Manhattan office leasing deal?"** — exercises `recommend_broker_for_deal`.

See `docs/demo-script.md` for the expected response shapes.

---

## Troubleshooting

### "Unexpected non-whitespace character after JSON" in Claude Desktop
Logs are leaking into stdout. Make sure you have commit `9d72a8f` or later — that fix routes structlog to stderr. Run `git log --oneline | head -5` to verify.

### MCP indicator doesn't show 9 tools
Claude Desktop config syntax error or wrong path. Run:

```bash
uv run --project <your-repo-path> python -m mcp_server.server < /dev/null
```

Should print a few JSON-RPC `notifications/message` lines to stdout. If it errors, fix that first.

### `health_check` returns `ml_freshness_warning: true`
The `ml.refresh` worker isn't running, or hasn't completed its first run yet. Check `/tmp/cre_ml.log`.

### Q1 returns empty `properties: []`
The market-name canonicalization didn't apply. Re-run `scripts/backfill.py` with the latest commit (the prefix-stripping fix is in `ingester/normalizer.py`).

### Snowflake connection fails
- Confirm `.env` has the right account / user / password
- If you're on a corporate VPN with Snowflake IP restrictions, you may need to allow your laptop's egress IP
- For prototype: use a service account with key-pair auth instead of password (see Snowflake docs)

### Neo4j keeps restarting
Check `docker compose logs neo4j`. Most common: GDS plugin version mismatch with Neo4j version. The repo pins both versions in `docker-compose.yml`; don't change them ad hoc.

### Background services keep running after I close my terminal
Kill them: `pkill -f "ingester.streaming"; pkill -f "ml.refresh"`.

---

## Mock-only setup (no Snowflake)

If you don't have Snowflake access, you can still run the MCP server against an empty graph or against fixture data. The `health_check`, `cypher_query`, and `traverse_graph` tools will work; the high-level NL tools will return `DEGRADED` with empty results.

For meaningful demo data, you'll need to seed Neo4j manually. There's no fixture loader in v1.0.0 — that's on the v1.1 roadmap.

---

## Hosting it for others remotely

Out of scope for this guide. The current setup uses **stdio transport** (one MCP server process per Claude Desktop session). To serve multiple users from one deployment, switch to **Streamable HTTP transport** (FastMCP supports it) and deploy to Cloud Run / Fly.io / Railway. See `docs/architecture.md` §13 for the migration path.

---

## Where to look next

- `docs/prd.md` — what this thing is supposed to do
- `docs/architecture.md` — how it's built
- `docs/api-contracts.md` — exact tool input/output schemas
- `docs/demo-script.md` — verbatim demo prompts + expected responses
- `RELEASE_NOTES.md` — what shipped in v1.0.0
- `docs/reviews/` — Cortex code-review findings per phase (interesting if you're studying SDLC pipelines)
