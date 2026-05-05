# Changelog

All notable changes to this project are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [1.0.0-hackathon] - 2026-05-05

### Added

- **Phase 1 (0e61f55):** Bootstrap MCP server with stdio transport, FastMCP auto-discovery, `health_check` tool (node/edge counts, Neo4j reachability), `cypher_query` escape-hatch tool, and `semantic_search` tool backed by sentence-transformers (all-MiniLM-L6-v2, 384-dim). Snowflake connector with env-file auth. Full backfill of five Snowflake tables (`CRE_BROKERS`, `CRE_PROPERTIES`, `CRE_LEASE_COMPS`, `CRE_PURSUITS`, `CRE_SPOC`) into Neo4j 5.15 + GDS via Docker Compose.
- **Phase 2 (1306883):** Streaming insight ingest pipeline — Snowflake Stream + Task on `CRE_MARKET_INSIGHTS`, `CRE_INSIGHTS_DELTA` staging table, long-running ingester (`ingester/streaming.py`) polling every 60s. Insight nodes upserted with 384-dim body embedding and `:ABOUT` edges to Market, Submarket, AssetClass, and Tenant nodes. ML freshness reporting in `health_check` (`latest_insight_age_minutes`).
- **Phase 3 (9366c82):** ML enrichment layer — Node2Vec embeddings (128-dim, GDS, stored as `node2vec_embedding`) on Broker, Property, and Tenant nodes; Louvain community detection (`community_id` on all projected nodes); link prediction via Adamic-Adar (`:PredictedLink` nodes, score threshold configurable). Three new MCP tools: `list_communities`, `predict_links`, `traverse_graph` (BFS, 200-node / 500-edge cap, max 3 hops).
- **Phase 4 (c82dc6b):** Three high-level intent-named tools answering the three canonical PRD questions: `find_matching_properties_for_insight` (Q1), `suggest_next_best_actions_for_deal` (Q2), `recommend_broker_for_deal` (Q3). Shared `ranker.py` with documented weight constants. `examples/claude_desktop_config.json` for Claude Desktop wiring. `scripts/demo.sh` end-to-end demo launcher. 304-test unit suite.
- **9 MCP tools total:** `health_check`, `cypher_query`, `semantic_search`, `list_communities`, `predict_links`, `traverse_graph`, `find_matching_properties_for_insight`, `suggest_next_best_actions_for_deal`, `recommend_broker_for_deal`.
- **Graph at demo:** 8190 Brokers, 20101 Properties, 10120 Leases, 10000 Pursuits, 50 Insights, 50 PredictedLinks, 39 Markets, 106 Submarkets in Neo4j.

### Changed

- **Phase 1.5 (2a41a6f) — Cortex review closures:** Cypher injection hardening (allowlist-only queries); `health_check` returns `DEGRADED` rather than exception when Neo4j is unreachable; `Client.name` KeyError fix in backfill normalizer.
- **Phase 2.5 (ece9b11) — Cortex review closures:** Cypher injection fix (parameterised queries); KeyError fix in streaming ingester; dimension-mismatch DEGRADED response in `semantic_search`; SQL idempotency for stream/task DDL.
- **Phase 3.5 (280a81a) — Cortex review closures:** Embedding property name unified (`node2vec_embedding`); GDS namespace corrected for Neo4j 5.15 API; live verification added to ML refresh worker; ML refresh wiring corrected.
- **Phase 4.5 (5737a2f) — Cortex review closures:** Cypher column name fixes (`deal_volume_usd`, `execution_date`); `demo.sh` embedding name corrected; Q2 stage filter logic corrected; API contract sync.

### Fixed

- **Phase 4.6 (497ced0) — Demo-blocker bug fixes:**
  - Q1 property query: fixed invalid `ORDER BY ... NULLS LAST` syntax (not supported in Neo4j 5.15); switched to `CASE WHEN` ordering. Q1 now returns 5+ Boston Office properties for the Microsoft insight.
  - Q1/Q2/Q3 broker responses: `Broker.firm` now populated (8165 of 8190 brokers have `firm`). Backfill derives firm from broker email domain where CRE_BROKERS row lacks explicit firm name.
  - Q1 market hierarchy: property-to-market query now uses substring match on submarket's parent market name, resolving the `boston` vs `back bay boston` hierarchy gap.
  - Q2 Pursuit schema: `outcome`, `asset_class`, `market`, and `probability` properties now written during backfill. Comparable query (`outcome IN ['Closed Won','Won']`) now matches; Q2 returns 3+ won-pursuit comparables with non-uniform similarity scores.
  - Q2 SPOC names: `Broker.name` backfill gap fixed; SPOC entries now show populated names.
  - Q3 scoring: `deal_volume_usd` column fix confirmed; top broker `deal_volume_score` strictly greater than bottom broker score.
  - `health_check` ML freshness: `MLRunMeta {key:'global'}` node written by ML refresh worker; `ml_freshness_warning` now returns `false` after ML run.

### Security

- Cypher injection mitigated via parameter binding and an allowlist on the `cypher_query` escape-hatch tool (Phase 1.5, Phase 2.5).
- `.env` file is gitignored; only `.env.example` is tracked. Snowflake credentials are never committed.
- MCP server connects to Neo4j read-only; no write-back path to Snowflake exists.

---

<!-- Unreleased placeholder for post-hackathon work -->
## [Unreleased]
