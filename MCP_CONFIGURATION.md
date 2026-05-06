# MCP Server Configuration — Complete Reference

Single source of truth for every way you can run the CRE Knowledge Graph MCP server.

If you only want to **use** an already-running server (someone else hosts it), jump to [§4 Connecting from a remote MCP client](#4-connecting-from-a-remote-mcp-client).

If you want to **run it yourself**, see [§2 Local stdio (Claude Desktop on your laptop)](#2-local-stdio-claude-desktop-on-your-laptop) or [§3 Remote streamable-http (host for cloud agents)](#3-remote-streamable-http-host-for-cloud-agents).

---

## 1. The 3 deployment modes at a glance

| Mode | Transport | Who connects | Auth | Tool count |
|---|---|---|---|---|
| **Local stdio** | child process spawned by client | Claude Desktop (or any MCP client) on the same machine | implicit (only the user who launched it) | **9** (incl. `cypher_query`) |
| **Remote streamable-http** | long-running HTTP server + Cloudflare Tunnel | Anyone with the public URL: cloud agents (Anthropic / OpenAI Agents SDK / LangChain), Claude Desktop's remote MCP feature | URL is the secret (~50 bits of entropy in random subdomain) | **8** (`cypher_query` hidden by default) |
| **Remote streamable-http with full surface** | same | same | same | **9** if `MCP_REMOTE_ALLOW_CYPHER=1` |

The 3 modes are switched by the `MCP_TRANSPORT` env var (or the `scripts/run_remote_mcp.sh` launcher which sets it for you).

---

## 2. Local stdio (Claude Desktop on your laptop)

This is the default. Claude Desktop spawns the MCP server as a child process; logs flow to stderr; JSON-RPC flows over stdout.

### Pre-reqs
- Docker Desktop running with Neo4j + GDS up (`docker compose up -d`)
- `uv` Python package manager installed
- `.env` populated with Snowflake + Neo4j credentials
- Backfill + ingester + ml.refresh have run at least once (graph populated)

### Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "cre-kg": {
      "command": "<ABSOLUTE_PATH_TO_UV>",
      "args": [
        "run",
        "--project",
        "<ABSOLUTE_PATH_TO_REPO>",
        "python",
        "-m",
        "mcp_server.server"
      ],
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "<your-neo4j-password>"
      }
    }
  }
}
```

**Replace 2 placeholders**:
- `<ABSOLUTE_PATH_TO_UV>` → output of `which uv` (typically `/Users/<you>/.local/bin/uv` or `/opt/homebrew/bin/uv`)
- `<ABSOLUTE_PATH_TO_REPO>` → absolute path to your cloned `cre-kg-mcp` directory

**Merging with existing servers**: if `claude_desktop_config.json` already has other entries inside `mcpServers`, just add the `cre-kg` key — don't replace the whole file.

### Restart Claude Desktop

Full quit (CMD+Q on macOS) and relaunch. The tools indicator (🔧) should show **9 cre-kg tools**: `health_check`, `cypher_query`, `semantic_search`, `find_matching_properties_for_insight`, `suggest_next_best_actions_for_deal`, `recommend_broker_for_deal`, `traverse_graph`, `list_communities`, `predict_links`.

### Test prompt
> "Run health_check."

If Claude calls the tool and you see graph counts, you're done.

---

## 3. Remote streamable-http (host for cloud agents)

Use this when another team / cloud-hosted agent / off-laptop client needs access. The server listens on local HTTP; Cloudflare Tunnel exposes it to the public internet over HTTPS with no port forwarding.

### Architecture

```
[ Cloud agent ] --HTTPS--> Cloudflare edge --QUIC--> cloudflared (your laptop) --HTTP--> uvicorn (mcp_server.server) --bolt--> Neo4j (docker)
```

### One-time setup

```bash
# Install cloudflared (once per machine)
brew install cloudflared
```

### Boot sequence (every time you want it online)

```bash
# Terminal 1 — long-running MCP HTTP server
bash scripts/run_remote_mcp.sh
# (Or detached:)
# nohup bash scripts/run_remote_mcp.sh > /tmp/cre_mcp_remote.log 2>&1 &

# Terminal 2 — quick tunnel (free, random subdomain)
cloudflared tunnel --url http://localhost:8080
# Look for: "Your quick Tunnel has been created!  https://<random-words>.trycloudflare.com"
```

The launcher script `scripts/run_remote_mcp.sh` reads `.env`, sets `MCP_TRANSPORT=streamable-http`, binds to `127.0.0.1:8080` by default, and runs the server.

### Environment variables that control remote mode

```bash
# In .env
MCP_TRANSPORT=streamable-http      # or "stdio" (default) or "sse"
MCP_HOST=127.0.0.1                 # bind address (cloudflared connects here)
MCP_PORT=8080                      # change if 8080 is taken
MCP_REMOTE_ALLOW_CYPHER=0          # set to 1 to expose cypher_query (NOT recommended)
```

### What changes in remote mode

1. `cypher_query` is hidden from `tools/list` (Cypher-injection blast radius is too broad over public internet).
2. DNS-rebinding protection is disabled (the tunnel hostname rotates; the tunnel itself is the trust boundary).
3. structlog still routes to stderr; uvicorn writes its own request logs to stderr too — none of it corrupts the JSON-RPC stream.

### To stop

```bash
pkill -f "cloudflared tunnel"
pkill -f "mcp_server.server"
```

---

## 4. Connecting from a remote MCP client

Once the server is running in remote mode and you have the Cloudflare URL, point any MCP client at `https://<random>.trycloudflare.com/mcp`. Examples:

### Anthropic SDK (Python)

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = "https://lounge-instances-lanka-compression.trycloudflare.com/mcp"

async with streamablehttp_client(URL) as (read, write, _):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool("recommend_broker_for_deal", {
            "market": "manhattan",
            "asset_class": "office",
            "service_line": "leasing",
        })
```

### OpenAI Agents SDK

```python
from agents import Agent, MCPServerStreamableHTTP

cre_kg = MCPServerStreamableHTTP(
    name="cre-kg",
    params={"url": "https://lounge-instances-lanka-compression.trycloudflare.com/mcp"},
)
await cre_kg.connect()

agent = Agent(
    name="CRE Broker Assistant",
    instructions="Answer with grounded data from the cre-kg tools.",
    mcp_servers=[cre_kg],
)
```

### LangChain MCP adapter

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient({
    "cre-kg": {
        "url": "https://lounge-instances-lanka-compression.trycloudflare.com/mcp",
        "transport": "streamable_http",
    }
})
tools = await client.get_tools()
```

### Claude Desktop (remote MCP)

```json
{
  "mcpServers": {
    "cre-kg-remote": {
      "url": "https://lounge-instances-lanka-compression.trycloudflare.com/mcp",
      "transport": "streamable-http"
    }
  }
}
```

### Postman

Import `examples/cre_kg_mcp.postman_collection.json`. Run "0. Protocol setup → Initialize" first; the test script auto-captures the session id. Then run any request.

### curl

See `scripts/test_remote.sh` — a 5-step bash exercise of the full handshake + a couple of tool calls.

---

## 5. The 9 tools (8 in remote mode)

| # | Tool | Purpose | Key inputs |
|---|------|---------|------------|
| 1 | `find_matching_properties_for_insight` | **Q1 workflow** — properties + brokers matching a market signal | `insight_id` OR `insight_query` |
| 2 | `suggest_next_best_actions_for_deal` | **Q2 workflow** — actions + comparables for a pursuit | `pursuit_id` |
| 3 | `recommend_broker_for_deal` | **Q3 workflow** — top brokers for deal context | `market`, `asset_class`, `service_line`, optional `my_broker_key` |
| 4 | `semantic_search` | Vector search over insight bodies | `query`, `top_k`, `filter` |
| 5 | `traverse_graph` | N-hop subgraph from a node (capped at 200 nodes / 500 edges / 3 hops) | `start_node_id`, `max_hops`, optional `target_labels` and `relationship_types` |
| 6 | `list_communities` | Top Louvain communities + dominant market/asset_class | `top_n` |
| 7 | `predict_links` | Top-k Adamic-Adar predicted edges from a node | `node_id`, `k` |
| 8 | `health_check` | Server status + graph counts + ML freshness | none |
| 9 | `cypher_query` | **Local-only** — escape hatch for arbitrary read-only Cypher | `query`, optional `params`, `read_only` (gated on `ALLOW_WRITE_CYPHER=1`) |

---

## 6. The new-insight agent loop (chained tool calls)

When the streaming ingester surfaces a new market-research insight, an agent should call the tools in this order:

```
                       semantic_search(query=insight.body, top_k=3)
                                          │
                                          ▼
                      find_matching_properties_for_insight(insight_id)
                                          │
                            ┌─────────────┼─────────────┐
                            ▼             ▼             ▼
                    properties[]   matching_brokers[]   insight context
                                                      (market, asset_class)
                                                            │
                                          ┌─────────────────┼────────────────┐
                                          ▼                                    ▼
                  recommend_broker_for_deal(market, asset_class)   traverse_graph(name::client,
                  → ranked broker list with                           relationship_types=[
                    deal_volume_score, community_match,                 SPOC_FOR, FOR, ABOUT,
                    production_tier                                     BELONGS_TO, HAS_SERVICE_LINE])
                                                                     → SPOC team members
```

The Postman folder **"3. Workflow: New Insight → Action"** wires these 4 calls with auto-extraction so each step's output feeds the next.

---

## 7. ID format reference (for traverse_graph)

| Entity | `start_node_id` format | Example |
|---|---|---|
| Broker | `email::<broker-email>` | `email::stephanie.bell@cbre.com` |
| Client | `name::<lowercase-name>` | `name::microsoft` |
| Tenant | `name::<lowercase-name>` (often shares key with Client) | `name::amazon` |
| Property | `id::<property-id>` | `id::PROP-000042` |
| Lease | `id::<comp-id>` | `id::COMP-007552` |
| Pursuit | `<pursuit-id>` (raw) | `PUR-0000001` |
| Insight | `<insight-id>` (raw) | `INS-20260319-001` |
| Market | `<lowercase-market-name>` | `manhattan`, `boston` |
| AssetClass | `<lowercase-asset-class>` | `office`, `industrial` |

---

## 8. Background services that must be running

The MCP server itself is **read-only** against Neo4j. For a meaningful demo, two additional long-running processes need to keep the graph fresh:

```bash
# Streaming ingester — polls Snowflake every 60s for new insights
nohup uv run python -m ingester.streaming > /tmp/cre_ingester.log 2>&1 &

# ML refresh — re-runs Node2Vec + Louvain + link-prediction every 10 min
nohup uv run python -m ml.refresh > /tmp/cre_ml.log 2>&1 &
```

The MCP server's `health_check` tool reports `last_ml_run_at` and `ml_freshness_warning: true` if the ML hasn't run in >15 min — that's how you know the ML worker died.

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Claude Desktop: "Unexpected non-whitespace character after JSON" | structlog leaking to stdout (older commits) | Upgrade past commit `9d72a8f` |
| Tools list missing in Claude Desktop | Wrong path in `claude_desktop_config.json` | Run `uv run --project <repo> python -m mcp_server.server < /dev/null` to verify boot |
| Remote: `Invalid Host header` | DNS rebinding still enabled | `MCP_TRANSPORT=streamable-http` should disable it; check `mcp_server/server.py` got the post-init transport_security override |
| Remote: 502/connection refused | Tunnel down OR MCP server crashed | `pgrep -f cloudflared`, `pgrep -f mcp_server`, restart whichever is missing |
| `health_check.ml_freshness_warning: true` | `ml.refresh` worker died | Check `/tmp/cre_ml.log`, restart |
| Q1 returns 0 properties | Market hierarchy gap (insight market doesn't link to property submarket) | Ensure `ingester/normalizer.py` has the prefix-stripping fix; re-run backfill |
| `recommend_broker_for_deal` returns 0 brokers | Market/asset_class mismatch (case sensitivity, canonical name) | Use lowercase: `manhattan` not `Manhattan`, `office` not `Office` |
| Postman: "Got session id" test fails | Server returning HTML 502 (tunnel down) | Re-verify base_url; restart tunnel |

---

## 10. Where each thing lives

| Path | What |
|---|---|
| `mcp_server/server.py` | Transport switch, tool registration, FastMCP setup |
| `mcp_server/tools/*.py` | One file per tool (auto-discovered) |
| `ingester/streaming.py` | Snowflake Stream → Neo4j ingester |
| `ml/refresh.py` | Scheduled ML pipeline (Node2Vec + Louvain + link prediction) |
| `scripts/run_remote_mcp.sh` | Boot remote-mode HTTP server |
| `scripts/test_remote.sh` | 5-step bash smoke test of the public endpoint |
| `examples/claude_desktop_config.json` | Local stdio config template |
| `examples/cre_kg_mcp.postman_collection.json` | 18 pre-built requests across 5 folders |
| `docs/REMOTE_INTEGRATION.md` | Hand to the team consuming the remote endpoint |
| `SETUP.md` | First-time-user installation walkthrough |
| `MCP_CONFIGURATION.md` | This file — runtime configuration reference |
