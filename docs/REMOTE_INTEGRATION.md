# Remote Integration Guide — CRE Knowledge Graph MCP Server

**For the other team building the cloud agent.** This server is hosted on a developer laptop and exposed to the public internet via Cloudflare Tunnel. Talk to it over MCP Streamable HTTP.

---

## Public endpoint

```
https://lounge-instances-lanka-compression.trycloudflare.com/mcp
```

> ⚠️ This URL changes each time the tunnel is restarted (it's a free Cloudflare quick tunnel). If you get connection errors, ping the host (Harish) to confirm the current URL. For a stable URL we'll need to upgrade to a named tunnel + custom domain.

> ⚠️ The tunnel only works while the host's laptop is on and `cloudflared` is running. There's no SLA. Treat this as dev/preview, not production.

## Auth model

**No bearer token** — the URL itself is the access secret (50+ bits of entropy in the random subdomain). Don't share the URL in public channels (Slack DMs / private repos only). If the URL leaks, the host can rotate it in seconds by restarting the tunnel.

## Transport

[**MCP Streamable HTTP**](https://modelcontextprotocol.io/specification/2024-11-05/basic/transports#streamable-http) (NOT the older SSE transport). All requests are `POST /mcp` with `Content-Type: application/json` and `Accept: application/json, text/event-stream`. Responses come as Server-Sent Events.

Session lifecycle:
1. `POST /mcp` with `initialize` method → response includes `mcp-session-id` header.
2. `POST /mcp` with `mcp-session-id` header + `notifications/initialized` (no response expected).
3. All subsequent requests must include `mcp-session-id: <id>` header.

## Tools exposed (8)

| Tool | Purpose | Key inputs |
|---|---|---|
| `health_check` | Server status + graph counts + ML freshness | none |
| `semantic_search` | Vector search over insight bodies | `query: string`, `top_k`, `filter` |
| `find_matching_properties_for_insight` | Q1 — properties + brokers matching an insight | `insight_id` OR `insight_query` |
| `suggest_next_best_actions_for_deal` | Q2 — actions + comparables for a pursuit | `pursuit_id` |
| `recommend_broker_for_deal` | Q3 — ranked broker list for deal context | `market`, `asset_class`, `service_line` |
| `traverse_graph` | N-hop subgraph from a start node | `start_node_id`, `max_hops` (≤3) |
| `list_communities` | Top Louvain communities + dominant market/asset | `top_n` |
| `predict_links` | Top-k Adamic-Adar predicted edges from a node | `node_id`, `k` |

Full input/output schemas: see `docs/api-contracts.md` in the [repo](https://github.com/ThirunagariHarish/cre-kg-mcp/blob/main/docs/api-contracts.md).

`cypher_query` is hidden in remote mode by default (Cypher injection blast radius is too large for public-internet exposure). If you need it, ask the host to set `MCP_REMOTE_ALLOW_CYPHER=1` and restart.

---

## Connecting from common SDKs

### Anthropic Python SDK with `streamable-http` MCP transport

```python
from anthropic import Anthropic
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def call_tool():
    url = "https://lounge-instances-lanka-compression.trycloudflare.com/mcp"
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"got {len(tools.tools)} tools")

            # call health_check
            result = await session.call_tool("health_check", {})
            print(result.content[0].text)

asyncio.run(call_tool())
```

Add to `requirements.txt`: `mcp>=1.27.0`.

### OpenAI Agents SDK

OpenAI's Agents SDK supports MCP servers via the `MCPServerStreamableHTTP` adapter (in `agents>=0.0.7`):

```python
from agents import Agent, MCPServerStreamableHTTP

cre_kg = MCPServerStreamableHTTP(
    name="cre-kg",
    params={"url": "https://lounge-instances-lanka-compression.trycloudflare.com/mcp"},
)
await cre_kg.connect()

agent = Agent(
    name="CRE Broker Assistant",
    instructions="You help CRE brokers with deal context, broker matching, and market insights.",
    mcp_servers=[cre_kg],
)
# ... run the agent ...
```

### LangChain with MCP

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient({
    "cre-kg": {
        "url": "https://lounge-instances-lanka-compression.trycloudflare.com/mcp",
        "transport": "streamable_http",
    }
})
tools = await client.get_tools()
# Use these tools with any LangGraph agent
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

### Raw curl (debugging)

```bash
URL="https://lounge-instances-lanka-compression.trycloudflare.com/mcp"

# Step 1 — initialize, capture session id
SESSION=$(curl -s -i -X POST "$URL" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"initialize","id":1,
       "params":{"protocolVersion":"2024-11-05","capabilities":{},
                 "clientInfo":{"name":"curl","version":"1"}}}' \
  | grep -i "mcp-session-id" | awk '{print $2}' | tr -d '\r')

# Step 2 — initialized notification
curl -s -X POST "$URL" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

# Step 3 — call any tool
curl -s -X POST "$URL" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","method":"tools/call","id":2,
       "params":{"name":"recommend_broker_for_deal",
                 "arguments":{"market":"manhattan","asset_class":"office","service_line":"leasing"}}}'
```

---

## Sample tool calls + expected shapes

### `health_check()`

```json
{
  "status": "OK",
  "neo4j_reachable": true,
  "gds": "2.6.9",
  "node_counts": {"Broker": 8190, "Property": 20101, "Insight": 50, ...},
  "last_ml_run_at": "2026-05-05T21:34:13.852000+00:00",
  "ml_freshness_warning": false
}
```

### `find_matching_properties_for_insight(insight_id="INS-20260319-001")`

Microsoft Boston insight:
```json
{
  "status": "OK",
  "insight": {"id": "INS-20260319-001", "market": "boston", "asset_class": "office"},
  "properties": [
    {"property": {"id": "id::PROP-...", "name": "..."}, "score": 0.8,
     "reasons": ["office asset class match", "Located in boston"]},
    ...
  ],
  "matching_brokers": [
    {"broker_id": "email::tyler.peterson@cushman&wakefield.com",
     "name": "Tyler Peterson", "firm": "Cushman & Wakefield",
     "score": 0.71, "reasons": ["Covers boston market"]},
    ...
  ]
}
```

### `recommend_broker_for_deal(market="manhattan", asset_class="office", service_line="leasing")`

```json
{
  "status": "OK",
  "deal_context": {"market": "manhattan", "asset_class": "office", "service_line": "leasing"},
  "brokers": [
    {"broker": {"id": "email::stephanie.bell@cbre.com", "name": "Stephanie Bell",
                "firm": "CBRE", "community_id": 48},
     "score": 0.65,
     "components": {"deal_volume_score": 1.0, "production_tier": "top-quartile",
                    "specialization_match": true, "community_match": false, ...},
     "reasons": ["Specializes in office"]}
  ]
}
```

---

## Operational notes

### Latency
Cloudflare adds ~30–60ms over the local 8–15ms call. Most tools complete in <500ms. `find_matching_properties_for_insight` can take 1–2s for high-fanout insights.

### Rate limits
Cloudflare Tunnel free tier has no published rate limit but isn't intended for production load. Stay under ~50 req/sec sustained.

### Data freshness
The graph rebuilds embeddings + communities + link prediction every 10 min. Expect up to 15 min lag from a new Snowflake insight to its appearance in `find_matching_properties_for_insight` results.

### What to do if requests start failing
1. Check `health_check` first — if the response is still 200 but graph counts dropped, ML or ingester died.
2. If the URL returns 502/connection errors, the tunnel is down — ping the host.
3. If you get "Method Not Allowed" or HTML responses, the host is restarting; wait 30s.

### How to upgrade off the quick tunnel
Long term, this should move to:
- Cloudflare named tunnel + a custom domain (stable URL, no random subdomain regeneration)
- Bearer-token auth or mTLS (revocable per-client credential)
- A small VPS or container deployment (no laptop dependency)

That's a 1–2 hour migration when there's product-side momentum.

---

## Contact

Repo: https://github.com/ThirunagariHarish/cre-kg-mcp (private — request access)
Host: harishlearning2@gmail.com
