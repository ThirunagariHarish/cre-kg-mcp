# Tech Plan — CRE Knowledge-Graph MCP Server

Each phase below is sized for a single focused Devin session. Phase boundaries are demoable. No phase touches >15 files. No phase mixes cross-stack concerns (e.g. Python ingester + MCP tool surface in the same phase).

Working directory: `/Users/harishkumar/Projects` (currently NOT a git repo — Phase 1 first task).

---

## Phase 1 — Bootstrap + Backfill + Minimal MCP Server

**Goal:** From `git clone` to a populated Neo4j and a Claude Desktop session that successfully calls `health_check` and `cypher_query`.

**Demoable at boundary?** Yes. Run `docker compose up -d`, run `make backfill`, open Claude Desktop, ask "Run health check on the CRE graph" and observe a populated response with non-zero node counts.

### Scope
- Initialize git repo + `.gitignore` + `README.md` + `.env.example`.
- Set up Python project: `pyproject.toml`, `uv` lockfile, dependencies (`snowflake-connector-python`, `neo4j`, `mcp`, `pydantic`, `apscheduler`, `python-dotenv`, `structlog`).
- Add `docker-compose.yml` with Neo4j 5.15 + GDS plugin, healthcheck, named volume, `.env`-driven password.
- Implement `ingester/snowflake_client.py` — auth, connection test, basic SELECT helpers.
- Implement `ingester/normalizer.py` — merge-key functions per entity (per `data-model.md` §4.1) + canonical_map.yaml stub.
- Implement `ingester/graph_writer.py` — Cypher MERGE templates + constraint/index bootstrap (run on first connect).
- Implement `ingester/backfill.py` — orchestrates backfill in locked order: BROKERS → PROPERTIES → LEASE_COMPS → PURSUITS → SPOC.
- Implement `mcp/server.py` — stdio MCP server skeleton; register `health_check` and `cypher_query`.
- Implement `mcp/tools/health_check.py` and `mcp/tools/cypher_query.py`.
- Implement `Makefile` with `bootstrap`, `backfill`, `mcp`, `down` targets.
- Add Claude Desktop config snippet to `README.md`.

### Files to create (count: 14, under cap)
1. `/Users/harishkumar/Projects/.gitignore`
2. `/Users/harishkumar/Projects/.env.example`
3. `/Users/harishkumar/Projects/README.md`
4. `/Users/harishkumar/Projects/pyproject.toml`
5. `/Users/harishkumar/Projects/docker-compose.yml`
6. `/Users/harishkumar/Projects/Makefile`
7. `/Users/harishkumar/Projects/ingester/__init__.py`
8. `/Users/harishkumar/Projects/ingester/snowflake_client.py`
9. `/Users/harishkumar/Projects/ingester/normalizer.py`
10. `/Users/harishkumar/Projects/ingester/canonical_map.yaml`
11. `/Users/harishkumar/Projects/ingester/graph_writer.py`
12. `/Users/harishkumar/Projects/ingester/backfill.py`
13. `/Users/harishkumar/Projects/mcp/server.py` + `mcp/tools/health_check.py` + `mcp/tools/cypher_query.py` (3 files; counted as 3 → total 14)

### Test plan
- `tests/test_normalizer.py` — table-driven tests for every merge-key function. Cases: email present, email absent, address with suite, taxonomy canonicalization, unknown taxonomy values.
- `tests/test_graph_writer.py` — uses `testcontainers-python` Neo4j (or skips with marker if Docker unavailable); asserts MERGE is idempotent across two runs.
- `tests/test_health_check.py` — mocks Neo4j driver; asserts DEGRADED behavior when driver raises.
- `tests/test_cypher_query.py` — asserts read_only=True rejects `CREATE`, `MERGE`, `DELETE` clauses via Neo4j-side error.
- Manual smoke: `make bootstrap` → `make backfill` → node counts roughly match table row counts (within 2% for dedup).

### Definition of Done (Cortex review checklist)
- [ ] `git init` complete, `.env` gitignored, `.env.example` checked in.
- [ ] `docker compose up -d neo4j` starts a healthy Neo4j with GDS plugin (`CALL gds.list()` returns rows).
- [ ] `make backfill` completes without unhandled exceptions and logs node counts.
- [ ] All 13 unique constraints + 7 lookup indexes + 4 vector indexes from `data-model.md` §3 exist after first run.
- [ ] `health_check` MCP tool returns `status: "OK"` with non-zero `Broker`, `Property`, `Lease`, `Pursuit` counts.
- [ ] `cypher_query` with `read_only: true` runs `MATCH (n) RETURN count(n)`; with `read_only: true` and a `CREATE` clause returns `status: "ERROR"`.
- [ ] Claude Desktop config snippet works copy-paste — Claude lists 2 tools.
- [ ] Unit tests pass: `pytest tests/` exits 0.
- [ ] `README.md` documents the <10-min setup path.

### Rollback
`docker compose down -v && rm -rf .venv` returns the host to clean state. Snowflake unaffected (read-only in this phase).

### Highest risks
- Neo4j GDS plugin version skew with Neo4j 5.15. **Mitigation:** pin `neo4j:5.15-community` and the matching GDS jar version explicitly in `docker-compose.yml`.
- ACCOUNTADMIN role permissions on `HACKATHON.PUBLIC` may be missing for SELECT on some tables. **Mitigation:** Phase 1 first runtime task is a `SELECT 1 FROM <each_of_5_tables>` probe with clear per-table error.

---

## Phase 2 — Streaming Insight Pipeline + Insight Node + `semantic_search`

**Goal:** Insert a row into `CRE_INSIGHTS_RAW` in Snowflake; observe the corresponding `:Insight` node and `ABOUT` edges in Neo4j within 15 minutes; call `semantic_search` and get embedding-ranked results.

**Demoable at boundary?** Yes. Use Snowflake worksheet to `INSERT` a test insight; ask Claude "what's the latest insight in the graph and what is it about?"; observe the new node and its tags.

### Scope
- Create Snowflake DDL for `CRE_INSIGHTS_RAW`, `CRE_INSIGHTS_DELTA`, `CRE_INSIGHTS_STREAM`, `CRE_INSIGHTS_TASK` (idempotent script).
- Implement `ingester/insight_consumer.py` — polls `CRE_INSIGHTS_DELTA WHERE processed=FALSE` every 60s, calls normalizer, writes `:Insight` + `ABOUT` edges, marks `processed=TRUE`.
- Implement `ingester/scheduler.py` — APScheduler with the 60s poll job (ML refresh job lands in Phase 3).
- Extend `ingester/normalizer.py` — `canonical_resolver(tag)` function returning `(label, name)` or None; warning log for unmapped tags.
- Add a tiny CPU-only embedding helper for `semantic_search` text queries: use `sentence-transformers/all-MiniLM-L6-v2` (384-dim) for query text → projected/padded to 128-dim to match Node2Vec, OR maintain a separate text-query path that searches Insight bodies via Cypher full-text and returns those nodes' embeddings as anchors.
  - **Decision:** keep it simple — `semantic_search(query_text=...)` for label `Insight` does Neo4j full-text on `body+title`, picks top match, then uses its embedding as anchor against the requested label. For non-Insight labels with no anchor, return `DEGRADED` with explanation.
- Implement `mcp/tools/semantic_search.py`.
- Extend `health_check` to include `latest_insight_age_minutes` and stale warning when >15 min.
- Add `scripts/insert_demo_insight.sql` for the demo.

### Files to create/touch (count: 8)
- New: `/Users/harishkumar/Projects/snowflake/insights_setup.sql`
- New: `/Users/harishkumar/Projects/scripts/insert_demo_insight.sql`
- New: `/Users/harishkumar/Projects/ingester/insight_consumer.py`
- New: `/Users/harishkumar/Projects/ingester/scheduler.py`
- New: `/Users/harishkumar/Projects/mcp/tools/semantic_search.py`
- Touch: `/Users/harishkumar/Projects/ingester/normalizer.py`
- Touch: `/Users/harishkumar/Projects/mcp/server.py` (register new tool)
- Touch: `/Users/harishkumar/Projects/mcp/tools/health_check.py` (freshness fields)

### Test plan
- `tests/test_canonical_resolver.py` — known tags resolve to canonical labels; unknown tags return None and log warning.
- `tests/test_insight_consumer.py` — fixture row in mock delta table; assert MERGE Insight + ABOUT edges; assert `processed=TRUE` after success; assert idempotency on re-run.
- Integration: insert two insights ~5 minutes apart; `health_check` reports `latest_insight_age_minutes < 5` after second one.
- `tests/test_semantic_search.py` — pre-populated graph with known embeddings; assert ordering by cosine similarity matches expected.

### Definition of Done
- [ ] Running `snowflake/insights_setup.sql` from a Snowflake worksheet creates Stream + Task without error and the Task is RESUMED.
- [ ] Inserting a test row into `CRE_INSIGHTS_RAW` results in an `:Insight` node and at least one `:ABOUT` edge in Neo4j within 15 minutes (typically <2 min with 60s ingester poll + 5 min Task).
- [ ] `health_check` reports `latest_insight_age_minutes` correctly; flags warning when >15.
- [ ] `semantic_search` with `label: "Insight"` and `query_text: "industrial absorption"` returns at least one matching Insight when one exists.
- [ ] Unmapped tag warnings appear in `health_check.warnings`.
- [ ] Unit + integration tests pass.

### Rollback
- `DROP TASK CRE_INSIGHTS_TASK; DROP STREAM CRE_INSIGHTS_STREAM; DROP TABLE CRE_INSIGHTS_DELTA;` (preserves CRE_INSIGHTS_RAW for replay).
- `MATCH (i:Insight) DETACH DELETE i;` in Neo4j.
- Revert `mcp/server.py` to remove `semantic_search` registration.

### Highest risks
- Snowflake Task scheduling minimum is 1 minute on standard accounts; `5 MINUTE` schedule is fine. Verify the warehouse `COMPUTE_WH` exists and has resume privileges under ACCOUNTADMIN. **Mitigation:** parameterize warehouse name via env var.

---

## Phase 3 — ML Enrichment + `traverse_graph`, `list_communities`, `predict_links`

**Goal:** Embeddings, communities, and predicted links exist on the graph; the three corresponding tools return populated results.

**Demoable at boundary?** Yes. Ask Claude "list the top 5 graph communities and their dominant markets" → populated. "Find brokers similar to <name>" → ranked results. "Show predicted broker-property affinities" → list with scores.

### Scope
- Implement `ingester/ml_enricher.py`:
  - Project graph via `gds.graph.project` over the relevant labels and relationships.
  - Run `gds.node2vec.write` (params per architecture §8.3) on Broker, Property, Tenant, Insight.
  - Run `gds.louvain.write` writing `community_id` to Broker, Property, Tenant, and synthesize `:Community` nodes + `:IN_COMMUNITY` edges.
  - Run link prediction: use `gds.beta.linkprediction.adamicAdar` or topological features pipeline; write top-N edges per Broker as `PREDICTED_AFFINITY` with `score`.
  - Drop projection at end of run.
- Wire ML refresh into `ingester/scheduler.py`: `IntervalTrigger(minutes=10)` + new-insight counter ≥50 override.
- Implement `mcp/tools/traverse_graph.py` with the 200-node/500-edge cap and 3-hop max.
- Implement `mcp/tools/list_communities.py`.
- Implement `mcp/tools/predict_links.py`.
- Extend `health_check` with `last_ml_run_at` + `ml_freshness_warning`.

### Files to create/touch (count: 7)
- New: `/Users/harishkumar/Projects/ingester/ml_enricher.py`
- New: `/Users/harishkumar/Projects/mcp/tools/traverse_graph.py`
- New: `/Users/harishkumar/Projects/mcp/tools/list_communities.py`
- New: `/Users/harishkumar/Projects/mcp/tools/predict_links.py`
- Touch: `/Users/harishkumar/Projects/ingester/scheduler.py`
- Touch: `/Users/harishkumar/Projects/mcp/server.py`
- Touch: `/Users/harishkumar/Projects/mcp/tools/health_check.py`

### Test plan
- `tests/test_ml_enricher.py` — small fixture graph (10 brokers, 30 properties); after enrichment assert every Broker/Property has `embedding` (length 128) and `community_id`.
- `tests/test_traverse_graph.py` — fixture graph; verify cap enforcement, hop counting, relationship-type filter.
- `tests/test_list_communities.py` — pre-populated `community_id` properties; assert sorting by size and `min_size` filter.
- `tests/test_predict_links.py` — pre-populated `:PREDICTED_AFFINITY` edges; assert ordering by score and `min_score` filter.
- Manual: `make ml-refresh` (one-shot CLI for forcing a run) completes in <3 min on the seed dataset.

### Definition of Done
- [ ] After one ML run, every `:Broker` and `:Property` node has a `embedding` array of length 128 and an integer `community_id`.
- [ ] At least one `:PREDICTED_AFFINITY` edge with a `score` property exists.
- [ ] At least one `:Community` synthetic node exists with size > 5.
- [ ] `traverse_graph` returns `truncated: true` and partial results when starting from a high-degree node.
- [ ] `list_communities` returns at least 3 communities of size ≥ 5.
- [ ] `predict_links` returns at least one prediction with score ≥ 0.5.
- [ ] `health_check.last_ml_run_at` reflects most recent successful run.
- [ ] Unit tests pass.

### Rollback
- `MATCH (n) REMOVE n.embedding, n.community_id;`
- `MATCH ()-[r:SIMILAR_TO|PREDICTED_AFFINITY|IN_COMMUNITY]-() DELETE r;`
- `MATCH (c:Community) DETACH DELETE c;`
- Disable ML scheduler job in `scheduler.py`.

### Highest risks
- GDS Community license restrictions on link prediction pipelines. **Mitigation:** if the pipeline-based `gds.beta.pipeline.linkPrediction.*` is Enterprise-only, fall back to `gds.linkprediction.adamicAdar.stream` — a topological scorer in Community — and write its top-K results as edges manually.
- Node2Vec memory on 500K-node projection. **Mitigation:** run on a subset projection (Broker, Property, Tenant + their direct relationships) rather than the full graph.

---

## Phase 4 — High-Level NL Tools + Demo

**Goal:** All three canonical PRD questions are answerable in Claude Desktop with graph-grounded named entities.

**Demoable at boundary?** Yes — this **is** the demo. Run the demo script end-to-end and produce three named-entity-grounded answers.

### Scope
- Implement `mcp/ranker.py` — shared ranking helpers (weighted-sum, normalization, reason-string builders).
- Implement `mcp/tools/find_matching_properties_for_insight.py`.
- Implement `mcp/tools/suggest_next_best_actions_for_deal.py`.
- Implement `mcp/tools/recommend_broker_for_deal.py`.
- Update `mcp/server.py` registration order per `api-contracts.md` §11.
- Author `docs/demo-script.md` — exact prompts, expected entity types, fallback wording if data is sparse.
- Add `claude_desktop_config.example.json` with the stdio server entry.
- Final `README.md` polish: <10-min setup steps verified.

### Files to create/touch (count: 7)
- New: `/Users/harishkumar/Projects/mcp/ranker.py`
- New: `/Users/harishkumar/Projects/mcp/tools/find_matching_properties_for_insight.py`
- New: `/Users/harishkumar/Projects/mcp/tools/suggest_next_best_actions_for_deal.py`
- New: `/Users/harishkumar/Projects/mcp/tools/recommend_broker_for_deal.py`
- New: `/Users/harishkumar/Projects/docs/demo-script.md`
- New: `/Users/harishkumar/Projects/claude_desktop_config.example.json`
- Touch: `/Users/harishkumar/Projects/mcp/server.py`

### Test plan
- `tests/test_ranker.py` — weighted ranking deterministic across re-runs; ties broken stably.
- `tests/test_find_matching_properties_for_insight.py` — fixture insight tagged "Industrial+Dallas"; assert returned properties are all in Dallas Industrial subgraph; assert empty-result path returns explanation.
- `tests/test_suggest_next_best_actions_for_deal.py` — fixture with one similar historical pursuit; assert it appears in `comparables`; assert fallback path when no comparables.
- `tests/test_recommend_broker_for_deal.py` — fixture with one active SPOC + one expired SPOC for the same client; assert active is ranked first and expired is included with `spoc_status: "expired"`.
- End-to-end demo dry run: 3 canonical questions answered with at least one graph-sourced named entity each.

### Definition of Done
- [ ] `find_matching_properties_for_insight` returns ranked properties with broker references for a known insight; empty case returns transparent explanation.
- [ ] `suggest_next_best_actions_for_deal` returns ≥1 historical comparable for a known pursuit; fallback path triggers cleanly when comparables are empty.
- [ ] `recommend_broker_for_deal` returns ≥2 ranked brokers with reason strings; expired SPOCs are flagged not silently dropped.
- [ ] Claude Desktop, after the example config is installed, lists all 9 tools.
- [ ] `docs/demo-script.md` exists with the 3 question prompts and expected response shape.
- [ ] Full demo runs in <2 minutes end-to-end with all 3 questions answered.
- [ ] Unit tests pass.

### Rollback
- Per-tool: remove registration from `mcp/server.py` and restart Claude Desktop.
- No data side-effects in this phase (read-only tools).

### Highest risks
- Empty-result paths on real Snowflake data. If a market has no leases for an asset class, Q1 returns empty — make sure the response is graceful and the demo script picks a market/asset class combo with data.
- Claude's tool-selection accuracy. **Mitigation:** keep tool descriptions explicit about user-intent verbs ("the user asks 'which properties...'") so Claude picks the right one.

---

## Cross-cutting: Demo dataset seeding

Per PRD §10 (embedding cold-start risk): before Phase 3 ML run, ensure ≥20 Insight rows in `CRE_INSIGHTS_RAW`. Provide `scripts/seed_insights.sql` with 25 representative rows covering 3 markets × 3 asset classes during Phase 2 work.

---

## Sprint sizing summary

| Phase | New files | Touched files | Total | Cap (15) | Single Devin session? |
|---|---|---|---|---|---|
| 1 | 14 | 0 | 14 | OK | Yes |
| 2 | 5 | 3 | 8 | OK | Yes |
| 3 | 4 | 3 | 7 | OK | Yes |
| 4 | 6 | 1 | 7 | OK | Yes |

No phase mixes Apex+LWC+React (N/A here — Python+Neo4j only) and no phase exceeds the 15-file cap.
