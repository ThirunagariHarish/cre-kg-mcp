# MCP Tool Surface — API Contracts

All tools are exposed via the Anthropic Python MCP SDK over **stdio**. Tool descriptions below are LLM-facing — they are what Claude reads to decide when to invoke each tool. Schemas use JSON Schema draft-7 idioms.

Common conventions:
- All responses include `status: "OK" | "DEGRADED" | "ERROR"` and `error: string?`.
- All ranked-list responses include `truncated: bool`.
- Times are ISO-8601 UTC.
- Node references use `{id: string, label: string, name: string}` (id = the merge_key for entity nodes, or `pursuit_id`/`insight_id`/`community_id` for those).

---

## 1. `health_check`

**Description (LLM-facing):** Verify the knowledge graph and ingestion pipeline are live and current. Returns node counts, edge counts, freshness of the most recent insight, and any pipeline warnings. Call this first when the user asks "is the system working" or before running a demo.

**Input schema:** `{}` (no parameters)

**Output:**
```json
{
  "status": "OK",
  "neo4j_reachable": true,
  "node_counts": { "Broker": 1240, "Property": 87234, "Tenant": 41200, "Insight": 312, "...": "..." },
  "edge_counts": { "BROKERED_BY": 145000, "ABOUT": 1280, "PREDICTED_AFFINITY": 5400, "...": "..." },
  "latest_insight_age_minutes": 8,
  "last_ml_run_at": "2026-05-05T14:32:11Z",
  "ml_freshness_warning": false,
  "warnings": ["3 unmapped insight tags in last 60 minutes"]
}
```

**Errors:** Never throws. If Neo4j is unreachable returns `status: "DEGRADED"` with `error` and `neo4j_reachable: false`.

---

## 2. `cypher_query` — DEBUG ONLY, DANGEROUS

**Description (LLM-facing):** Execute an arbitrary Cypher query against the knowledge graph. **DESTRUCTIVE OPERATION:** this can read or modify graph data. Only use this when the user explicitly asks for a raw graph query or when other tools cannot satisfy the request. Prefer `traverse_graph` or `semantic_search` for normal exploration. The result is returned as a list of records.

**Input schema:**
```json
{
  "type": "object",
  "properties": {
    "query": { "type": "string", "description": "Cypher query text" },
    "params": { "type": "object", "description": "Optional Cypher parameters", "additionalProperties": true },
    "read_only": { "type": "boolean", "default": true, "description": "If true, query is run in a READ session and writes will fail" }
  },
  "required": ["query"]
}
```

**Output:**
```json
{
  "status": "OK",
  "records": [ { "key1": "value1", "...": "..." } ],
  "row_count": 23,
  "execution_ms": 145
}
```

**Error modes:**
- `CypherSyntaxError` → `status: "ERROR"`, `error: "Cypher syntax: ..."`
- Write attempted in read_only mode → `status: "ERROR"`, `error: "Read-only mode rejected write clause"`
- Query timeout (>10s) → `status: "ERROR"`, `error: "Query exceeded 10s timeout"`

**Hackathon caveat in tool description:** flagged as DESTRUCTIVE so Claude defers to it sparingly. Production deployments must remove this tool or restrict to a read-only Neo4j role.

---

## 3. `semantic_search`

**Description (LLM-facing):** Find graph nodes semantically similar to either a text query or an anchor node, using node embeddings. Use this to answer "find brokers like X" or "find properties similar to this one" or "find historical insights related to this topic".

**Input schema:**
```json
{
  "type": "object",
  "properties": {
    "query_text": { "type": "string", "description": "Free-text query (will be embedded by the server using a small CPU model). Mutually exclusive with anchor_node_id." },
    "anchor_node_id": { "type": "string", "description": "ID of an existing node whose embedding is the search anchor." },
    "label": { "type": "string", "enum": ["Broker", "Property", "Tenant", "Insight"], "description": "Restrict results to this label." },
    "k": { "type": "integer", "minimum": 1, "maximum": 50, "default": 10 },
    "min_score": { "type": "number", "default": 0.0, "description": "Cosine similarity floor; results below this are dropped." }
  },
  "required": ["label"],
  "oneOf": [{"required": ["query_text"]}, {"required": ["anchor_node_id"]}]
}
```

**Output:**
```json
{
  "status": "OK",
  "results": [
    { "node": {"id": "email::jane@cbre.com", "label": "Broker", "name": "Jane Liu"}, "score": 0.91 },
    { "node": {"id": "email::tom@jll.com", "label": "Broker", "name": "Tom Patel"}, "score": 0.87 }
  ],
  "truncated": false
}
```

**Error modes:**
- Anchor node not found → `status: "ERROR"`, `error: "Anchor node not found"`
- Embeddings not yet computed → `status: "DEGRADED"`, `error: "Embeddings not yet generated; run ML enrichment"`, `results: []`

---

## 4. `find_matching_properties_for_insight` (Q1)

**Description (LLM-facing):** Given a market-research insight (by ID or natural-language description), return a ranked list of properties in the relevant market and asset class, plus the brokers who have transacted on those properties. Use this when the user pastes or references a new insight and asks "which of my properties and brokers does this affect?" or "who should I reach out to based on this trend?".

**Input schema:**
```json
{
  "type": "object",
  "properties": {
    "insight_id": { "type": "string", "description": "ID of an Insight node already in the graph." },
    "insight_text": { "type": "string", "description": "Free-text insight description; embedded and matched against existing Insight/Market/AssetClass embeddings." },
    "limit": { "type": "integer", "minimum": 1, "maximum": 50, "default": 15 }
  },
  "oneOf": [{"required": ["insight_id"]}, {"required": ["insight_text"]}]
}
```

**Output:**
```json
{
  "status": "OK",
  "insight": { "id": "ins_abc123", "title": "DFW Industrial absorption surge Q2 2026" },
  "matched_market": "dallas-fort worth",
  "matched_asset_class": "industrial",
  "properties": [
    {
      "property": { "id": "id::P-9921", "label": "Property", "name": "1450 Logistics Pkwy" },
      "score": 0.84,
      "reasons": ["Industrial asset class match", "Located in dallas-fort worth", "Recent lease activity"],
      "brokers": [
        { "node": {"id": "email::jane@cbre.com", "name": "Jane Liu"}, "rel": "BROKERED_BY", "deal_volume_usd": 145000000 }
      ]
    }
  ],
  "matching_brokers": [
    {
      "broker_id": "email::jane@cbre.com",
      "name": "Jane Liu",
      "firm": "CBRE",
      "score": 0.88,
      "reasons": ["Covers dallas-fort worth market", "Specializes in industrial asset class"]
    }
  ],
  "truncated": false
}
```

**Error modes:**
- No properties matched → `status: "OK"`, `properties: []`, with explanation in `warnings: ["No properties found in dallas industrial subgraph"]`
- Insight ID not found → `status: "ERROR"`, `error: "Insight not found"`

---

## 5. `suggest_next_best_actions_for_deal` (Q2)

**Description (LLM-facing):** Given a deal (Pursuit) at its current pipeline stage, suggest concrete next actions grounded in similar historical pursuits that progressed from the same stage. Returns the historical comparable pursuits, the brokers who closed them, and graph-derivable signals about what unblocked them. Use this when the user asks "what should I do next on this deal" or "this deal is stalled, help".

**Input schema:**
```json
{
  "type": "object",
  "properties": {
    "pursuit_id": { "type": "string" },
    "comparable_count": { "type": "integer", "minimum": 1, "maximum": 10, "default": 3 }
  },
  "required": ["pursuit_id"]
}
```

**Note:** PRD originally specified structured `recommended_actions: [{action, rationale, confidence, supporting_pursuits}]`; this v1 uses flat strings + separate `comparables` for simplicity.

**Note:** Stage history is not tracked in v1; comparables include final outcome only. The `transitioned_through_stages` field from early PRD drafts is not present in v1 output.

**Output:**
```json
{
  "status": "OK",
  "pursuit": { "id": "pur_551", "stage": "Proposal Sent", "client": "Acme Corp" },
  "comparables": [
    {
      "pursuit": { "id": "pur_201", "stage": "Closed Won", "outcome": "Closed Won" },
      "similarity_score": 0.80,
      "closing_broker": { "id": "email::tom@jll.com", "name": "Tom Patel" },
      "service_line": "tenantrep"
    }
  ],
  "suggested_actions": [
    "Schedule follow-up with primary client contact (3/3 comparables advanced after such a meeting)",
    "Loop in Tom Patel — closed similar Office tenant rep deal in same submarket"
  ],
  "fallback_used": false,
  "truncated": false
}
```

**Error modes:**
- Pursuit not found → `status: "ERROR"`, `error: "Pursuit not found"`
- No similar comparables → `status: "OK"`, `fallback_used: true`, `suggested_actions: ["Insufficient historical comparables; consider brokers in {community} for {market} {asset_class}"]`, `comparables: []`

---

## 6. `recommend_broker_for_deal` (Q3)

**Description (LLM-facing):** Recommend the best-fit broker(s) for a deal given its market, asset class, and service line. Ranks by deal volume in market, specialization match, active SPOC assignments, and graph community alignment. Use this when the user asks "who should work this deal?" or "best broker for X market Y asset class Z service line".

**Input schema:**
```json
{
  "type": "object",
  "properties": {
    "market": { "type": "string", "description": "Market name; will be canonicalized" },
    "asset_class": { "type": "string" },
    "service_line": { "type": "string" },
    "client_name": { "type": "string", "description": "Optional. If provided, SPOC matches receive a boost." },
    "my_broker_key": { "type": "string", "description": "Optional. Broker key of the requesting broker. If provided, community overlap with that broker is computed and exposed as community_overlap_with_me." },
    "k": { "type": "integer", "minimum": 1, "maximum": 20, "default": 5 }
  },
  "required": ["market", "asset_class", "service_line"]
}
```

**Output:**
```json
{
  "status": "OK",
  "deal_context": { "market": "atlanta", "asset_class": "retail", "service_line": "tenantrep", "client": "Acme Corp" },
  "brokers": [
    {
      "broker": { "id": "email::jane@cbre.com", "name": "Jane Liu", "firm": "CBRE", "community_id": 7 },
      "score": 0.88,
      "components": {
        "deal_volume_score": 0.92,
        "production_tier": "top-quartile",
        "specialization_match": true,
        "market_coverage_match": true,
        "spoc_status": "active",
        "community_match": true,
        "community_overlap_with_me": true,
        "predicted_affinity_score": 0.61
      },
      "reasons": [
        "Active SPOC for Acme Corp on TenantRep service line",
        "Top-quartile deal volume in Atlanta Retail (last 12 months)",
        "In same Louvain community as requesting broker"
      ]
    }
  ],
  "truncated": false
}
```

**Notes:**
- `my_broker_key`: pass the requesting broker's merge key (e.g. `"email::jane@cbre.com"`) to enable community overlap scoring.
- `community_overlap_with_me`: `true` when the candidate broker is in the same Louvain community as the requesting broker (`my_broker_key`).
- `production_tier`: derived from `deal_volume_score` quartile breakpoints — `"top-quartile"` (≥0.75), `"second-quartile"` (≥0.50), `"third-quartile"` (≥0.25), `"fourth-quartile"` (below 0.25).
- `community_id`: exposed on the `broker` sub-object per PRD STORY-4.3 AC.

**Error modes:**
- Unknown market/asset class → `status: "OK"`, `brokers: []`, `warnings: ["Market 'XYZ' not in canonical map"]`
- Broker has expired SPOC → broker is included with `spoc_status: "expired"` and ranked below brokers with active SPOCs (never silently dropped)

---

## 7. `traverse_graph`

**Description (LLM-facing):** Return the n-hop neighborhood around a starting node, optionally filtered by relationship types and target labels. Use this for exploratory questions the high-level tools do not cover, e.g. "show all tenants connected to this landlord's portfolio". Results are capped at **200 nodes / 500 edges** per call; if hit, you receive `truncated: true` and should narrow your start node or filter.

**Input schema:**
```json
{
  "type": "object",
  "properties": {
    "start_node_id": { "type": "string" },
    "start_label": { "type": "string", "description": "Used to disambiguate id; required if id alone is not unique." },
    "max_hops": { "type": "integer", "minimum": 1, "maximum": 3, "default": 2 },
    "relationship_types": { "type": "array", "items": {"type": "string"}, "description": "Whitelist of edge types to follow. If empty, all are followed." },
    "target_labels": { "type": "array", "items": {"type": "string"}, "description": "Whitelist of node labels to return. If empty, all are returned." },
    "node_cap": { "type": "integer", "minimum": 10, "maximum": 200, "default": 200 },
    "edge_cap": { "type": "integer", "minimum": 10, "maximum": 500, "default": 500 }
  },
  "required": ["start_node_id"]
}
```

**Output:**
```json
{
  "status": "OK",
  "nodes": [
    {"id": "id::P-9921", "label": "Property", "name": "1450 Logistics Pkwy"},
    {"id": "name::acme corp", "label": "Tenant", "name": "Acme Corp"}
  ],
  "edges": [
    {"from": "id::L-77", "to": "id::P-9921", "type": "ON"},
    {"from": "id::L-77", "to": "name::acme corp", "type": "TENANT_IS"}
  ],
  "truncated": false,
  "node_count": 2,
  "edge_count": 2
}
```

**Error modes:**
- Start node not found → `status: "ERROR"`, `error: "Start node not found"`
- Truncation hit → `status: "OK"`, `truncated: true`, partial result returned with note in `warnings`

---

## 8. `list_communities`

**Description (LLM-facing):** List Louvain communities discovered in the graph with their size and dominant attributes. Useful for debugging and for answering "what natural market clusters exist?". Read-only.

**Input schema:**
```json
{
  "type": "object",
  "properties": {
    "min_size": { "type": "integer", "default": 5 },
    "limit": { "type": "integer", "minimum": 1, "maximum": 100, "default": 20 },
    "include_members_sample": { "type": "boolean", "default": false }
  }
}
```

**Output:**
```json
{
  "status": "OK",
  "computed_at": "2026-05-05T14:32:11Z",
  "communities": [
    {
      "community_id": 7,
      "size": 184,
      "dominant_market": "dallas-fort worth",
      "dominant_asset_class": "industrial",
      "members_sample": [
        {"id": "email::jane@cbre.com", "label": "Broker", "name": "Jane Liu"}
      ]
    }
  ],
  "truncated": false
}
```

**Error modes:**
- Communities not yet computed → `status: "DEGRADED"`, `error: "Louvain has not yet run"`, `communities: []`

---

## 9. `predict_links`

**Description (LLM-facing):** Return the top-k predicted edges (broker → property, broker → tenant) ranked by link-prediction score. Surfaces latent affinities not visible from explicit deal history. **Hackathon caveat:** scores are best-effort at this data scale; treat as a brainstorming aid, not a precision recommendation.

**Input schema:**
```json
{
  "type": "object",
  "properties": {
    "from_node_id": { "type": "string", "description": "Optional. If given, only return predictions originating from this node." },
    "from_label": { "type": "string", "enum": ["Broker"] },
    "to_label": { "type": "string", "enum": ["Property", "Tenant"] },
    "min_score": { "type": "number", "default": 0.5 },
    "k": { "type": "integer", "minimum": 1, "maximum": 50, "default": 10 }
  },
  "required": ["to_label"]
}
```

**Output:**
```json
{
  "status": "OK",
  "model_version": "node2vec-128d-2026-05-05",
  "predictions": [
    {
      "from": {"id": "email::jane@cbre.com", "label": "Broker", "name": "Jane Liu"},
      "to": {"id": "id::P-9921", "label": "Property", "name": "1450 Logistics Pkwy"},
      "score": 0.78
    }
  ],
  "caveat": "Link-prediction accuracy is best-effort at hackathon data volumes",
  "truncated": false
}
```

**Error modes:**
- No predictions ≥ `min_score` → `status: "OK"`, `predictions: []`
- Link prediction not yet run → `status: "DEGRADED"`, `error: "Link prediction has not yet run"`

---

## 10. Frontend / Programmatic Client Signatures

Even though the primary host is Claude Desktop (stdio JSON-RPC), the tools are reusable from any MCP-compliant client. Reference Python client signatures (illustrative — implementation by Devin):

```python
class CREGraphClient:
    async def health_check(self) -> HealthCheckResponse: ...
    async def cypher_query(self, query: str, params: dict | None = None,
                           read_only: bool = True) -> CypherResponse: ...
    async def semantic_search(self, label: NodeLabel, *,
                              query_text: str | None = None,
                              anchor_node_id: str | None = None,
                              k: int = 10, min_score: float = 0.0) -> SemanticSearchResponse: ...
    async def find_matching_properties_for_insight(self, *,
                                                   insight_id: str | None = None,
                                                   insight_text: str | None = None,
                                                   limit: int = 15) -> InsightMatchResponse: ...
    async def suggest_next_best_actions_for_deal(self, pursuit_id: str,
                                                 comparable_count: int = 3) -> NextBestActionResponse: ...
    async def recommend_broker_for_deal(self, *, market: str, asset_class: str,
                                        service_line: str, client_name: str | None = None,
                                        k: int = 5) -> BrokerRecommendResponse: ...
    async def traverse_graph(self, start_node_id: str, *, start_label: str | None = None,
                             max_hops: int = 2,
                             relationship_types: list[str] | None = None,
                             target_labels: list[str] | None = None,
                             node_cap: int = 200, edge_cap: int = 500) -> TraverseResponse: ...
    async def list_communities(self, *, min_size: int = 5, limit: int = 20,
                               include_members_sample: bool = False) -> CommunitiesResponse: ...
    async def predict_links(self, *, to_label: Literal["Property","Tenant"],
                            from_node_id: str | None = None,
                            min_score: float = 0.5, k: int = 10) -> LinkPredictionResponse: ...
```

---

## 11. Tool Registration Order in MCP Server

Tools are registered in this order so Claude's tool-selection prompt sees the highest-intent tools first (improves selection accuracy):

1. `find_matching_properties_for_insight`
2. `suggest_next_best_actions_for_deal`
3. `recommend_broker_for_deal`
4. `semantic_search`
5. `traverse_graph`
6. `list_communities`
7. `predict_links`
8. `health_check`
9. `cypher_query` (last — destructive escape hatch)
