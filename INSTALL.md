# Install Guide — CRE Knowledge Graph MCP Server v1.0.0-hackathon

Get the full system running in under 5 minutes on macOS.

---

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Docker Desktop | 4.x+ | https://www.docker.com/products/docker-desktop |
| `uv` | 0.4+ | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Claude Desktop | Latest | https://claude.ai/download |
| macOS | 13 Ventura+ | — |

Verify before starting:

```bash
docker --version          # Docker version 4.x.x or higher
uv --version              # uv 0.4.x or higher
which uv                  # note this path — you'll need it in step 4
```

---

## Step 1 — Clone and configure credentials

```bash
git clone <repo-url>
cd Projects
cp .env.example .env
```

Open `.env` in any editor and fill in:

```
SNOWFLAKE_ACCOUNT=<your-account>
SNOWFLAKE_USER=<your-user>
SNOWFLAKE_PASSWORD=<your-password>
SNOWFLAKE_ROLE=ACCOUNTADMIN
SNOWFLAKE_DATABASE=HACKATHON
SNOWFLAKE_SCHEMA=PUBLIC
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=hackathon_local_only
```

The `.env` file is gitignored and never committed.

---

## Step 2 — Bootstrap (Neo4j + Python deps)

```bash
make bootstrap
```

This installs all Python dependencies via `uv sync` and starts Neo4j 5.15 Community with the GDS plugin via Docker Compose. It waits up to 3 minutes for `CALL gds.version()` to succeed.

Verify Neo4j is healthy:

```bash
docker compose ps
# cre-neo4j should show status "healthy"
```

Open Neo4j Browser at http://localhost:7474 (user: `neo4j`, password: value from `.env`).

---

## Step 3 — Backfill the graph

```bash
make backfill
```

Loads all five Snowflake tables in locked order: `CRE_BROKERS` → `CRE_PROPERTIES` → `CRE_LEASE_COMPS` → `CRE_PURSUITS` → `CRE_SPOC`. Expect ~3-5 minutes on a standard laptop.

Verify in Neo4j Browser:

```cypher
MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt ORDER BY cnt DESC
```

Expected: Broker ~8190, Property ~20101, Lease ~10120, Pursuit ~10000, Market 39, Submarket 106.

---

## Step 4 — Connect Claude Desktop

Find your `uv` path:

```bash
which uv
# Example output: /Users/yourname/.local/bin/uv
```

Open (or create) the Claude Desktop config file:

```
~/Library/Application Support/Claude/claude_desktop_config.json
```

Merge the following block into the `mcpServers` object (replace the `uv` path and project path with your actual values):

```json
{
  "mcpServers": {
    "cre-kg": {
      "command": "/Users/yourname/.local/bin/uv",
      "args": [
        "run",
        "--project",
        "/Users/yourname/Projects",
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

The exact snippet (pre-filled for this machine) is also in `examples/claude_desktop_config.json`.

Fully quit Claude Desktop (Cmd+Q), then re-open it. After restart you should see **9 MCP tools** in Claude's tool inventory.

---

## Step 5 — Verify the demo end-to-end

Ask Claude these three prompts in order. Each should return a structured, graph-grounded response with named entities from the real dataset — not generic placeholders.

**Prompt 1 (Q1 — properties from insight):**
```
Based on the latest Dallas Industrial absorption insight, what are the matching properties and brokers I can reach out to?
```
Expected: 3+ properties with non-zero scores, broker names with `firm` populated.

**Prompt 2 (Q2 — next best actions):**
```
Based on my deal PUR-001 in its current state, what actions can I take?
```
Expected: Won-pursuit comparables with non-uniform similarity scores, broker names who closed them.

**Prompt 3 (Q3 — broker recommendation):**
```
Who is the best broker to work with me on an Industrial deal in Dallas for tenant representation?
```
Expected: 5 brokers ranked by deal volume, `production_tier` populated, `community_id` present.

---

## Troubleshooting

### Neo4j healthcheck fails / Docker container not starting

```bash
docker compose logs neo4j
```

Common causes:
- Port 7474 or 7687 already in use — stop any other Neo4j instance or change the port in `docker-compose.yml`.
- Docker Desktop not running — launch Docker Desktop and wait for the whale icon to stop animating.
- Insufficient memory — Neo4j GDS requires at least 4 GB RAM allocated to Docker. Open Docker Desktop > Settings > Resources and increase memory.

### MCP tools not appearing in Claude Desktop

1. Confirm the MCP server starts cleanly in isolation: `uv run python -m mcp_server.server` — it should block without errors.
2. Confirm the `uv` path in `claude_desktop_config.json` matches `which uv` exactly.
3. Confirm the `--project` path points to the directory that contains `pyproject.toml`.
4. Check Claude Desktop logs: `~/Library/Logs/Claude/mcp*.log`.
5. Fully quit Claude Desktop (Cmd+Q is not enough if it minimises to the menu bar — right-click the Dock icon and choose Quit).

### Snowflake auth fails during backfill

```
snowflake.connector.errors.DatabaseError: 250001: Failed to connect to DB
```

- Confirm `SNOWFLAKE_ACCOUNT` format: use `<orgname>-<accountname>` (e.g. `rodbnov-hl98478`), not the full URL.
- Confirm `SNOWFLAKE_ROLE=ACCOUNTADMIN` — the backfill requires full read access to `HACKATHON.PUBLIC`.
- Run `uv run python -c "from ingester.snowflake_client import get_connection; get_connection()"` to isolate the auth error.

### Backfill completes but graph is empty

- Confirm `.env` is loaded: `uv run python -c "import os; from dotenv import load_dotenv; load_dotenv(); print(os.getenv('NEO4J_PASSWORD'))"` should print your password.
- Check backfill logs for `ERROR` lines — a Snowflake row-count mismatch above 2% tolerance will log a warning but not abort.
- Re-run `make backfill` — the backfill uses MERGE and is fully idempotent.
