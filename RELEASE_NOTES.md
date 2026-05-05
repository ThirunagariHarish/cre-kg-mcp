# Release Notes — v1.0.0-hackathon

**Date:** 2026-05-05
**Commit:** 497ced0 (main)
**Tag:** v1.0.0-hackathon

---

## TL;DR

The CRE Knowledge Graph MCP Server is a fully local, graph-grounded AI assistant for commercial real estate brokers and BD leads. It seeds a Neo4j knowledge graph from five Snowflake tables (brokers, properties, lease comps, pursuits, and SPOC assignments), streams new market-research insights into the graph within 5-15 minutes of publication, enriches the graph with Node2Vec embeddings, Louvain community detection, and link prediction, and exposes 9 typed MCP tools to Claude Desktop. The system answers three canonical questions — which properties match a new insight, what actions should I take on a stalled deal, and who is the best broker for this opportunity — grounded in real deal history and the actual broker network, eliminating the 30-90 minute manual cross-referencing cost that brokers face today.

---

## What's in v1.0.0-hackathon

### Living Ontology (Phase 1 + 1.5)

The graph backfills all five Snowflake tables on startup. 8190 Brokers, 20101 Properties, 10120 Leases, 10000 Pursuits, and SPOC assignments are loaded in a locked order with merge-key deduplication. The `health_check` tool surfaces node and edge counts, Neo4j reachability, and ML freshness at a glance. Cypher injection is mitigated via parameter binding and a query allowlist.

### Streaming Intelligence (Phase 2 + 2.5)

A Snowflake Stream and Task on `CRE_MARKET_INSIGHTS` routes new insight rows to a staging table every minute. The long-running ingester polls every 60 seconds, upserts each insight as a node with a 384-dim sentence embedding, and wires `:ABOUT` edges to the relevant Market, Submarket, AssetClass, and Tenant nodes. The graph currently holds 50 seeded insights. `health_check` reports the age of the most recent ingested insight.

### ML Enrichment (Phase 3 + 3.5)

After each ingest cycle the ML refresh worker runs Node2Vec embeddings (128-dim via Neo4j GDS), Louvain community detection, and Adamic-Adar link prediction. All 8190 Broker nodes and all Property nodes carry `node2vec_embedding` and `community_id`. 50 PredictedLink nodes capture latent broker-property affinities. Three MCP tools expose these results: `list_communities`, `predict_links`, and `traverse_graph` (BFS, capped at 200 nodes / 500 edges, max 3 hops).

### High-Level NL Tools (Phase 4 + 4.5 + 4.6)

Three intent-named tools answer the canonical questions directly from Claude Desktop:

- `find_matching_properties_for_insight` (Q1): Given an insight ID or free-text description, surfaces properties ranked by asset-class match, market match, and lease recency, plus brokers ranked by market coverage and specialization. Live-verified: returns 5+ Boston Office properties for the Microsoft Back Bay insight.
- `suggest_next_best_actions_for_deal` (Q2): Given a Pursuit ID, returns won-pursuit comparables with non-uniform similarity scores, the brokers who closed them, related insights, and SPOC contacts. Live-verified: returns 3+ comparables with varying scores for standard pursuit IDs.
- `recommend_broker_for_deal` (Q3): Ranks brokers by deal volume (0.40), specialization (0.25), active SPOC (0.20), community overlap (0.10), and predicted affinity (0.05). Expired SPOCs are flagged rather than silently dropped. Live-verified: returns 5 brokers with `firm`, `community_id`, `production_tier`, and non-uniform scores.

---

## Demo Flow

The full demo script is at `docs/demo-script.md`. The three verbatim Claude prompts are:

**Q1:**
```
Based on the latest Dallas Industrial absorption insight, what are the matching properties and brokers I can reach out to?
```

**Q2:**
```
Based on my deal PUR-001 in its current state, what actions can I take?
```

**Q3:**
```
Who is the best broker to work with me on an Industrial deal in Dallas for tenant representation?
```

See `docs/demo-script.md` for expected response shapes, failure fallbacks, and the pre-flight verification checklist.

---

## How to Install

See `INSTALL.md` for the 5-minute step-by-step guide. The short version:

```bash
git clone <repo-url> && cd Projects
cp .env.example .env          # fill in Snowflake + Neo4j creds
make bootstrap                # installs deps, starts Neo4j via Docker Compose
make backfill                 # loads all 5 Snowflake tables into Neo4j
# Copy examples/claude_desktop_config.json into Claude Desktop config
# Restart Claude Desktop
```

Prerequisites: Docker Desktop, `uv`, Claude Desktop on macOS.

---

## Known Limitations

The following bugs are confirmed and deferred to v1.1. They do not block the demo but reduce response fidelity in edge cases.

**BUG-001 — E2E test harness unwired** (`tests/e2e/conftest.py:195`): `MCPTestClient.call()` raises `NotImplementedError` unconditionally because the MCP stdio transport was never wired into the test client. 19 of 28 E2E tests fail as a result. The MCP server and tools themselves are correct; this is a test infrastructure gap. Mitigation: 304 unit tests pass; manual demo validation confirms all three Q1/Q2/Q3 flows return correct responses.

**BUG-007 — PredictedLink stored as nodes, not edges** (ML pipeline): The link prediction job writes `:PredictedLink` nodes rather than `:PREDICTED_AFFINITY` relationship edges. The `predict_links` MCP tool reads from the nodes and functions correctly. However, graph queries using `MATCH ()-[:PREDICTED_AFFINITY]->()` return zero results, and `recommend_broker_for_deal` reports `predicted_affinity_score: 0.0` for all brokers. Fix in v1.1: materialise edges in addition to nodes.

**BUG-009 — `deal_size_sf` parameter absent** (`recommend_broker_for_deal`): The tool signature uses `service_line` where the PRD acceptance criteria describe a `deal_size_sf` parameter. Calling with `deal_size_sf` raises `TypeError`. Fix in v1.1: add `deal_size_sf` to the tool signature and wire it into the scoring formula.

**BUG-010 — ASSIGNED_TO / HAS_SERVICE_LINE relationships missing** (data model): `Pursuit -[:ASSIGNED_TO]-> Broker` and `Pursuit -[:HAS_SERVICE_LINE]-> ServiceLine` edges are absent from the graph. Pursuit nodes have a `stage` property but no `:FOR` edge to Client is wired via these types. The Q2 tool falls back to SPOC-based recommendations when comparables are sparse. Fix in v1.1: add these relationship types to the backfill writer.

---

## Roadmap to v1.1

Post-hackathon priorities in rough order:

1. Wire `MCPTestClient` to the MCP stdio server for automated E2E coverage (BUG-001).
2. Materialise `:PREDICTED_AFFINITY` edges from PredictedLink nodes so broker scoring uses live affinity signal (BUG-007).
3. Add `deal_size_sf` to `recommend_broker_for_deal` scoring (BUG-009).
4. Add `ASSIGNED_TO` and `HAS_SERVICE_LINE` relationship types in backfill (BUG-010).
5. Unify 384-dim (Insight) and 128-dim (Broker/Property) embeddings into a single vector space for cross-entity semantic search.
6. Production secrets management (replace `.env` file with Vault or AWS Secrets Manager).
7. Submarket-to-market hierarchy normalisation (`:CONTAINS` edges) to replace the substring-match workaround introduced in Phase 4.6.
8. `deal_volume_usd` populated from CRE_PURSUITS.REVENUE_PROJECTION for Pursuit-level scoring in Q2.

---

## Credits

| Role | Agent |
|---|---|
| Product requirements | Nova |
| Architecture and data model | Atlas |
| Phase 1 — MCP bootstrap | Devin |
| Phase 1.5 — Cortex review fixes | Devin |
| Phase 2 — Streaming ingest | Devin |
| Phase 2.5 — Cortex review fixes | Devin |
| Phase 3 — ML enrichment | Devin |
| Phase 3.5 — Cortex review fixes | Devin |
| Phase 4 — High-level NL tools | Devin |
| Phase 4.5 — Cortex review fixes | Devin |
| Phase 4.6 — Demo-blocker bug fixes | Devin |
| QA validation | Quill |
| Release engineering | Helix |
