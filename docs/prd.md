# CRE Ontology MCP Server — Product Requirements Document

| Field | Value |
|---|---|
| Title | CRE Ontology Knowledge Graph MCP Server |
| Owner | harishlearning2@gmail.com |
| Date | 2026-05-05 |
| Status | Draft v1 |
| Mode | Hackathon Prototype |

---

## 1. Problem Statement

Commercial real estate brokers and BD leads work across fragmented data: lease comp history lives in one table, the broker network in another, the active deal pipeline in a third, and market research insights arrive asynchronously from a separate team. When a broker asks "who should I call for this deal?" or "what does this new insight mean for my pipeline?", they must manually cross-reference four or five data sources and rely on institutional memory. This costs 30–90 minutes per non-trivial question and introduces errors when the answer depends on relationships that span multiple tables (e.g., a broker who covered a similar deal, in the same submarket, for a tenant with overlapping credit profile).

The current workaround is ad-hoc Snowflake SQL queries run by an analyst, or a Slack message to a senior broker who "knows people." Neither is fast enough for live deal conversations or market-research-driven outreach.

---

## 2. Target Persona

**Primary:** CRE Broker / BD Lead at a brokerage firm.
- Uses Claude Desktop daily for drafting and research.
- Knows CRE domain deeply; does not write SQL or graph queries.
- Needs answers grounded in real deal history and the actual broker network, not generic LLM hallucinations.
- Measures success by: speed of outreach after a new market insight lands, quality of broker recommendations, and next-best-action clarity on stalled deals.

**Secondary:** Sales Operations / Data Admin who configures the MCP server and monitors the streaming pipeline.

---

## 3. Goals and Non-Goals

### Goals
- Answer, with graph-grounded context, the three canonical NL questions:
  - Q1: Given a new market-research insight, surface matching properties and brokers to contact.
  - Q2: Given a deal in its current pipeline stage, recommend next-best actions grounded in similar historical deals and the broker network.
  - Q3: Given a deal's characteristics, identify the best-fit broker based on production history, market coverage, specialization, and SPOC assignments.
- Build and incrementally maintain a CRE-domain ontology in Neo4j, seeded from five Snowflake tables, updated within 5–15 minutes of new insight landing.
- Enrich the graph with ML: node embeddings (similarity), community detection (market clustering), and link prediction (broker–property–tenant affinity).
- Expose the graph and ML results to Claude Desktop via an MCP server with typed, discoverable tools.
- Be end-to-end runnable on a macOS laptop within 10 minutes of `git clone`.

### Non-Goals
- Write-back to Snowflake from Claude.
- Production-grade security (SSO, secrets management beyond an env file, audit logging).
- Multi-tenant isolation or role-based access control.
- Mobile or web UI beyond Claude Desktop.
- Full GNN retraining pipelines (Node2Vec/GraphSAGE prototype only).
- Link prediction accuracy guarantees (must run end-to-end; accuracy is best-effort given hackathon data volume).

---

## 4. Solution Overview (Product Terms)

The system has three layers, each exposed to Claude as a capability — not as infrastructure decisions.

**Layer 1 — Living Ontology.** A background process reads all five Snowflake tables on startup and builds a CRE knowledge graph in Neo4j. Every entity (broker, property, tenant, lease, deal, insight) becomes a node; every meaningful business relationship becomes a typed edge. This graph is the single source of truth for grounded answers.

**Layer 2 — Streaming Intelligence.** When the market research team publishes a new insight, it lands in Snowflake. A Snowflake Stream and Task detects the change and signals the ingester within 5–15 minutes. The ingester upserts the new Insight node, resolves which Markets, Asset Classes, Properties, and Tenants it relates to, and wires the edges. The graph is always near-current.

**Layer 3 — ML Enrichment.** After each ingestion cycle, the graph is enriched: node embeddings capture semantic similarity between brokers and properties; community detection clusters the market by natural deal-flow groups; link prediction surfaces latent broker–tenant–property affinities not visible from explicit edges alone. These enrichments are stored back on the nodes and edges as properties the retrieval tools can rank by.

**Layer 4 — MCP Tool Surface.** The MCP server exposes a small set of high-level, intent-named tools to Claude. Claude never writes Cypher; it calls tools with natural-language parameters. The tools traverse the graph, apply ML-scored ranking, and return structured context that Claude uses to ground its answer.

---

## 5. CRE Ontology Overview

### Entities (Nodes)

| Entity | Source Table(s) | Key Attributes |
|---|---|---|
| Broker | CRE_BROKERS, CRE_SPOC | name, firm, markets, specializations, deal volume, certifications |
| Property | CRE_PROPERTIES | address, submarket, asset class, size, ownership, occupancy, financials, sustainability |
| Tenant | CRE_LEASE_COMPS | name, industry, credit profile |
| Landlord | CRE_LEASE_COMPS, CRE_PROPERTIES | name, portfolio |
| Lease | CRE_LEASE_COMPS | rent, TI, concessions, term, execution date |
| Pursuit | CRE_PURSUITS | stage, probability, revenue projection, win/loss, service lines |
| Client | CRE_PURSUITS, CRE_SPOC | name, account type |
| Market | CRE_BROKERS, CRE_SPOC, CRE_PROPERTIES | name, region |
| Submarket | CRE_PROPERTIES | name |
| AssetClass | CRE_BROKERS, CRE_SPOC, CRE_PROPERTIES | type (office, industrial, retail, multifamily, etc.) |
| ServiceLine | CRE_PURSUITS, CRE_SPOC | name (leasing, capital markets, PM, etc.) |
| Firm | CRE_BROKERS | name, type |
| Insight | Streaming (Snowflake table via Stream+Task) | content, source, timestamp, tags |

### Relationships (Edges)

| Relationship | From → To | Business Meaning |
|---|---|---|
| REPRESENTS | Broker → Client | SPOC assignment by service line |
| COVERS | Broker → Market | Geographic market coverage |
| SPECIALIZES_IN | Broker → AssetClass | Production specialization |
| BELONGS_TO | Broker → Firm | Employment / affiliation |
| LOCATED_IN | Property → Submarket | Physical location |
| PART_OF | Submarket → Market | Geographic hierarchy |
| CLASSIFIED_AS | Property → AssetClass | Asset type |
| ON | Lease → Property | Lease executed on this property |
| TENANT_IS | Lease → Tenant | Tenant in the lease |
| LANDLORD_IS | Lease → Landlord | Landlord in the lease |
| BROKERED_BY | Lease → Broker | Broker who transacted the deal |
| FOR | Pursuit → Client | BD opportunity for this client |
| ASSIGNED_TO | Pursuit → Broker | Broker responsible for pursuit |
| IN_STAGE | Pursuit → (stage value) | Pipeline stage |
| ABOUT | Insight → Market / AssetClass / Property / Tenant | What the insight concerns |
| SPOC_FOR | Broker → Client (via ServiceLine, geography, AssetClass, expiration) | Single point of contact assignment |
| SIMILAR_TO | Broker ↔ Broker / Property ↔ Property | ML-derived embedding similarity (weighted edge) |
| PREDICTED_AFFINITY | Broker ↔ Property / Broker ↔ Tenant | ML link prediction score |
| IN_COMMUNITY | Broker / Property → Community | Louvain community membership |

---

## 6. Epics and User Stories

### EPIC-1: Snowflake Connect and Backfill

**Goal:** Seed the Neo4j graph from all five static Snowflake tables so the MCP server has a complete starting ontology.

---

**STORY-1.1 — Snowflake Connector Setup** | Size: S

As a Sales Ops Admin, I want the ingester to authenticate to Snowflake using env-file credentials so that no secrets are hardcoded and setup takes under 5 minutes.

Acceptance Criteria:

```gherkin
Given the env file contains SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD, SNOWFLAKE_ROLE, SNOWFLAKE_DATABASE, SNOWFLAKE_SCHEMA
When the ingester starts
Then it connects to HACKATHON.PUBLIC without error and logs "Snowflake connection OK" within 10 seconds

Given an incorrect password is supplied in the env file
When the ingester starts
Then it logs a clear authentication error and exits with a non-zero code rather than silently hanging
```

---

**STORY-1.2 — Full Backfill of Five Tables into Neo4j** | Size: M

As a CRE Broker, I want all brokers, properties, leases, pursuits, and SPOC assignments loaded into the graph at startup so that my first question to Claude is answered from real data, not an empty graph.

Acceptance Criteria:

```gherkin
Given the five Snowflake tables have data (CRE_BROKERS, CRE_PROPERTIES, CRE_LEASE_COMPS, CRE_PURSUITS, CRE_SPOC)
When the ingester completes the initial backfill
Then Neo4j contains node counts matching source table row counts (within a 2% tolerance for deduplication) and all defined relationship types exist with at least one edge

Given a Property appears in both CRE_PROPERTIES and CRE_LEASE_COMPS with the same identifier
When the ingester loads both tables
Then exactly one Property node exists in Neo4j (no duplicates), with attributes merged from both sources
```

---

**STORY-1.3 — Health Check MCP Tool** | Size: XS

As a Sales Ops Admin, I want a `health_check` MCP tool so that I can confirm the graph is populated and the MCP server is live before running a demo.

Acceptance Criteria:

```gherkin
Given the MCP server is running and Neo4j is populated
When Claude calls the `health_check` tool
Then the tool returns node counts by label, edge counts by type, last ingestion timestamp, and status "OK"

Given Neo4j is unreachable
When Claude calls the `health_check` tool
Then the tool returns status "DEGRADED" with a human-readable error — it does not throw an unhandled exception into Claude's context
```

---

### EPIC-2: Streaming Insight Ingest

**Goal:** New market research insights arriving in Snowflake are reflected in the graph within 5–15 minutes.

---

**STORY-2.1 — Snowflake Stream and Task Detection** | Size: S

As a Market Research Analyst, I want new rows I insert into the insights table to automatically trigger graph updates so that the broker's Claude session reflects the latest intelligence within 15 minutes.

Acceptance Criteria:

```gherkin
Given a Snowflake Stream is defined on the insights source table and a Task polls it on a schedule
When a new insight row is inserted into the source table
Then the Task fires within the configured interval and delivers the new row to the ingester

Given no new rows have arrived since the last Task run
When the Task fires
Then it completes with no-op and logs "No new insights" without creating spurious graph updates
```

---

**STORY-2.2 — Insight Node Upsert and Edge Wiring** | Size: M

As a CRE Broker, I want a newly streamed insight automatically linked to the relevant markets, asset classes, and properties in the graph so that when I ask Claude about a new trend, it already knows which of my properties and brokers are affected.

Acceptance Criteria:

```gherkin
Given a new Insight row arrives with tags referencing "Office", "Downtown Submarket", and "Tenant ABC"
When the ingester processes the row
Then an Insight node is created (or upserted if the same insight ID already exists) with ABOUT edges to the matching AssetClass, Submarket, and Tenant nodes

Given an Insight references a Market that does not yet exist as a node
When the ingester processes the row
Then a new Market node is created and linked, rather than the insight being dropped or the ingester erroring
```

---

**STORY-2.3 — Freshness Verification** | Size: XS

As a Sales Ops Admin, I want the `health_check` tool to report the age of the most recent ingested insight so that I can confirm the 5–15 minute SLO is being met during the demo.

Acceptance Criteria:

```gherkin
Given an insight was inserted into Snowflake 8 minutes ago
When Claude calls `health_check`
Then the response includes "latest_insight_age_minutes: 8" (within 1-minute rounding) and the status does not show a staleness warning

Given no insight has been ingested in the last 20 minutes
When Claude calls `health_check`
Then the response includes a staleness warning: "latest_insight_age exceeds 15-minute SLO"
```

---

### EPIC-3: ML Enrichment

**Goal:** The graph is enriched with embeddings, community labels, and link-prediction scores that retrieval tools can use for ranked results.

---

**STORY-3.1 — Node Embeddings for Broker and Property Similarity** | Size: L

As a CRE Broker, I want the system to identify brokers and properties that are "similar" based on the graph structure and attributes so that Claude can recommend comparable deals and contacts I might not have thought of.

Acceptance Criteria:

```gherkin
Given the graph has been populated with at least 10 Broker nodes and 50 Property nodes
When the ML enrichment job runs
Then each Broker node has an `embedding` vector property and each Property node has an `embedding` vector property stored in Neo4j

Given two brokers who share the same Market, AssetClass, and have transacted on overlapping Property types
When `semantic_search` is called with one broker as the anchor
Then the other broker appears in the top-5 similar results ranked by embedding cosine similarity
```

---

**STORY-3.2 — Community Detection over the Graph** | Size: M

As a CRE Broker, I want brokers and properties grouped into natural market communities so that when I ask about a deal cluster, Claude surfaces the right peer group rather than unrelated nodes.

Acceptance Criteria:

```gherkin
Given the full graph is populated and embeddings have been computed
When Louvain community detection runs
Then each Broker, Property, and Tenant node has a `community_id` property assigned

Given community detection has run
When Claude calls `recommend_broker_for_deal` for a deal in Market X
Then the tool filters candidates to the community containing Market X before ranking, and the response notes the community grouping
```

---

**STORY-3.3 — Link Prediction: Broker–Property–Tenant Affinity** | Size: L

As a CRE Broker, I want the system to surface latent affinities between brokers, properties, and tenants that are not yet connected by an explicit deal edge so that Claude can suggest outreach I would not have identified from the existing data alone.

Acceptance Criteria:

```gherkin
Given a Broker node and a Property node with no existing BROKERED_BY path between them
When link prediction runs
Then a PREDICTED_AFFINITY edge is created between them if the prediction score exceeds the configured threshold, with a `score` property stored on the edge

Given the hackathon dataset is small
When link prediction completes
Then at least one PREDICTED_AFFINITY edge exists in the graph and Claude can retrieve it via `find_matching_properties_for_insight` — accuracy is best-effort, not guaranteed
```

Note: Link prediction quality is explicitly flagged as best-effort at hackathon data volumes. The story is "must run end-to-end" not "must be accurate."

---

### EPIC-4: MCP Tool Surface

**Goal:** Claude has a set of typed, intent-named tools that traverse the graph and return grounded context for the three canonical questions.

---

**STORY-4.1 — `find_matching_properties_for_insight` Tool** | Size: M

As a CRE Broker, I want to ask "based on this market insight, which properties and brokers should I contact?" and get a ranked, graph-grounded answer so that I can act on new intelligence in minutes instead of hours.

Acceptance Criteria:

```gherkin
Given an Insight node exists in the graph tagged with AssetClass "Industrial" and Market "Dallas"
When Claude calls `find_matching_properties_for_insight` with the insight ID or a natural-language description of the insight
Then the tool returns a ranked list of Properties in the Dallas Industrial subgraph, with the Broker(s) who have covered those properties, sorted by embedding similarity to the insight context

Given no properties exist in the matching market/asset class
When the tool is called
Then it returns an empty result set with a human-readable explanation ("No properties found in Dallas Industrial matching this insight") rather than an error
```

---

**STORY-4.2 — `suggest_next_best_actions_for_deal` Tool** | Size: M

As a CRE Broker, I want to ask "what actions should I take on this deal right now?" and receive recommendations grounded in similar historical pursuits and the broker network so that I make progress on stalled deals faster.

Acceptance Criteria:

```gherkin
Given a Pursuit node at stage "Proposal Sent" with a Client in the Office asset class in Chicago
When Claude calls `suggest_next_best_actions_for_deal` with the pursuit ID
Then the tool returns: (a) top 3 similar historical Pursuits that progressed past "Proposal Sent," (b) the actions taken on those pursuits as graph-derivable attributes, and (c) the broker(s) who closed them

Given the pursuit has no similar historical comparables in the graph
When the tool is called
Then the tool returns a transparent message noting "Insufficient historical comparables; showing brokers with highest Chicago Office community score" rather than fabricating actions
```

---

**STORY-4.3 — `recommend_broker_for_deal` Tool** | Size: M

As a CRE Broker or BD Lead, I want to ask "who is the best broker for this deal?" and get a ranked recommendation based on production, market coverage, specialization, and SPOC status so that I assign the right person without relying on gut feel.

Acceptance Criteria:

```gherkin
Given a deal with AssetClass "Retail", Market "Atlanta", and ServiceLine "Tenant Representation"
When Claude calls `recommend_broker_for_deal` with those parameters
Then the tool returns a ranked list of Brokers with: their community_id, deal volume in the matching market, active SPOC assignments for overlapping clients, and any PREDICTED_AFFINITY edges to properties in scope

Given a broker has an expired SPOC assignment for the relevant client
When the tool evaluates that broker
Then the expired SPOC is flagged as expired in the output and the broker is ranked lower than one with an active SPOC — it is not silently excluded
```

---

**STORY-4.4 — `traverse_graph` and `semantic_search` Escape-Hatch Tools** | Size: S

As a CRE Broker, I want to ask exploratory questions that the high-level tools do not cover — such as "show me all tenants connected to this landlord's portfolio" — and have Claude traverse the graph to answer them.

Acceptance Criteria:

```gherkin
Given a natural-language query that does not match a named tool's intent
When Claude uses `traverse_graph` with a starting node type and relationship path specification
Then the tool returns the subgraph up to 3 hops from the starting node, formatted as a readable list of nodes and relationships

Given a query involving semantic similarity ("find brokers similar to John Smith")
When Claude calls `semantic_search` with a text anchor or node ID
Then the tool uses stored embedding vectors to return the top-N most similar nodes of the requested label, ranked by cosine similarity score
```

---

### EPIC-5: Claude Desktop Integration and Demo

**Goal:** The full system runs on a macOS laptop and answers the three canonical NL questions correctly in a live demo.

---

**STORY-5.1 — Claude Desktop MCP Configuration** | Size: S

As a Sales Ops Admin, I want to register the MCP server in Claude Desktop's config file so that Claude automatically discovers all tools at startup without manual tool injection.

Acceptance Criteria:

```gherkin
Given the MCP server process is running on localhost and the Claude Desktop config file references it
When Claude Desktop is launched
Then Claude lists all five MCP tools (find_matching_properties_for_insight, suggest_next_best_actions_for_deal, recommend_broker_for_deal, traverse_graph, semantic_search, health_check) as available in its tool inventory

Given the MCP server process is not running
When Claude Desktop is launched
Then Claude displays a degraded-tools warning rather than crashing, and the user can still use Claude for non-graph tasks
```

---

**STORY-5.2 — End-to-End Demo Script Validation** | Size: S

As the hackathon presenter, I want a documented demo script that proves all three canonical questions are answered correctly with graph-grounded responses so that judges can verify the system is not hallucinating.

Acceptance Criteria:

```gherkin
Given the system is fully running (Neo4j populated, ML enrichment done, MCP server live, Claude Desktop connected)
When the presenter asks Q1 ("Based on [insight X], what are the matching properties and brokers I can reach out to?")
Then Claude's response cites specific Property names and Broker names pulled from the graph, not generic placeholders

When the presenter asks Q2 ("Based on this deal in its current state, what actions can I take?")
Then Claude's response references at least one historical comparable Pursuit by name or ID from the graph

When the presenter asks Q3 ("Who is the best broker to work with me on this deal?")
Then Claude's response ranks at least two named Brokers with a stated reason grounded in graph attributes (deal volume, market, SPOC status)
```

---

## 7. Non-Functional Requirements

| Requirement | Target | Hackathon Shortcut Allowed |
|---|---|---|
| Graph freshness | New insight reflected in Neo4j within 5–15 minutes of Snowflake insert | Polling interval can be set to 5 min; sub-minute not required |
| Scale | Designed for 100K–500K nodes, low millions of edges | Single Neo4j instance; no clustering needed for hackathon |
| Auth | Snowflake ACCOUNTADMIN credentials in `.env` file | Flagged as tech debt; acceptable for prototype |
| Demo setup time | Full system running in <10 min after `git clone` on macOS | Docker Compose for Neo4j acceptable |
| Observability | `health_check` MCP tool; structured logs to stdout | No external monitoring dashboards required |
| WCAG / accessibility | N/A (no custom UI; all interaction via Claude Desktop) | — |
| MCP compliance | Tools must be valid MCP tool definitions discoverable by any MCP client | Must not be Claude-specific hacks |

---

## 8. Out-of-Scope for v1

- Write-back to Snowflake (Claude can read, not write).
- RBAC or permission-set-level access control on graph nodes.
- Multi-tenant graph partitioning.
- Full GNN training pipelines beyond Node2Vec/GraphSAGE prototype.
- Link prediction accuracy SLOs (best-effort at hackathon data volume).
- Web or mobile UI.
- Automated retraining triggered by data drift.
- Production secrets management (Vault, AWS Secrets Manager, etc.).
- AppExchange / Salesforce integration.

---

## 9. Phasing Recommendation

| Phase | Time-box | Deliverable | Exit Criteria |
|---|---|---|---|
| Phase 1 | Day 1 AM | Snowflake → Neo4j backfill + `health_check` + `cypher_query` + `semantic_search` MCP tools live | `health_check` returns populated node counts; `semantic_search` returns results |
| Phase 2 | Day 1 PM – Day 2 AM | Snowflake Stream+Task → Neo4j insight upserts; freshness confirmed | Insert a test insight row; verify Neo4j reflects it within 15 min |
| Phase 3 | Day 2 | ML enrichment: embeddings on Broker + Property nodes; Louvain communities; link prediction edges | Each Broker and Property has `embedding` and `community_id` properties; at least one PREDICTED_AFFINITY edge exists |
| Phase 4 | Day 2 PM – Day 3 | High-level tools (`find_matching_properties_for_insight`, `suggest_next_best_actions_for_deal`, `recommend_broker_for_deal`); Claude Desktop wiring; demo script run-through | All three canonical questions answered with graph-grounded named entities |

---

## 10. Open Risks

| Risk | Description | Mitigation Hint (for Atlas) |
|---|---|---|
| Entity resolution | Same Property or Broker may appear with different key values across tables (e.g., address format vs. property ID). Duplicates will degrade graph traversal quality. | Flag for Atlas to define a merge key strategy per entity type at ingestion. |
| Data quality of streamed insights | Insight rows from the research team may have inconsistent tagging (market names, asset class labels) that prevents correct edge wiring. | Atlas should build a normalization/canonicalization step before upsert. |
| Embedding cold-start | With only a handful of Insight nodes initially, embeddings will have low variance and similarity scores will be unreliable. | Flag to demoing team: seed at least 20 insights before running ML enrichment. |
| Neo4j → Claude latency | Large subgraph traversals returned to Claude context may hit MCP response-size limits or slow the demo. | Atlas should cap `traverse_graph` result size and paginate. |
| Link prediction accuracy | Hackathon dataset is too small for meaningful link prediction. Model may produce near-random scores. | Explicitly communicated as best-effort in Story-3.3. Do not demo link prediction as a precision feature. |

---

## 11. Locked vs Ambiguous

| Item | Status | Notes |
|---|---|---|
| MCP host: Claude Desktop primary | Locked | Designed for any MCP client; Claude Desktop is demo target |
| Graph store: Neo4j | Locked | Single instance; no clustering |
| Snowflake account and tables | Locked | rodbnov / hl98478, HACKATHON.PUBLIC, ACCOUNTADMIN |
| Streaming mechanism: Snowflake Stream + Task | Locked | Task polls; ingester consumes |
| Freshness SLO: 5–15 minutes | Locked | Not sub-minute |
| ML scope: embeddings + community detection + link prediction | Locked | Link prediction is end-to-end only; accuracy is best-effort |
| Scale: hundreds of thousands of rows over 12 months | Locked | Single Neo4j instance sufficient |
| Three canonical NL questions | Locked | See Section 6 Epics 4–5 |
| Hackathon mode (not production) | Locked | No RBAC, no SSO, env-file auth |
| Entity resolution strategy (merge keys) | Ambiguous | Needs Atlas to define per-entity deduplication key before Story-1.2 build |
| Insight tagging schema | Ambiguous | Research team's tagging conventions unknown; normalization logic TBD |
| Embedding algorithm choice (Node2Vec vs GraphSAGE) | Ambiguous | Atlas to decide based on Neo4j GDS library availability |
| ML enrichment trigger (scheduled vs event-driven) | Ambiguous | After streaming ingest or on a fixed schedule? Atlas to decide |
| `traverse_graph` result size cap | Ambiguous | Atlas to define max nodes/edges returned before truncation |
| Demo dataset seeding (minimum insight count for ML) | Ambiguous | Recommend 20+ insights; exact threshold TBD |
