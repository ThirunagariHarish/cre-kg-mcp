# CRE Knowledge Graph — Demo Runbook

**Audience:** Hackathon presenter / demo operator
**Last updated:** 2026-05-05
**Pre-condition:** Phase 4 + Phase 3.5 + Phase 4.5 fixes have all landed and the implementation is wired end-to-end.

---

## Pre-flight Checklist

Complete these steps in order before opening Claude Desktop.

### 1. Start Docker Compose

```bash
cd $REPO_ROOT
docker compose up -d
```

Wait approximately 30 seconds for Neo4j to finish initializing, then verify Neo4j Browser is accessible:

- Open: http://localhost:7474
- Login: neo4j / (password from your .env NEO4J_PASSWORD)
- Run in the browser: `MATCH (n) RETURN labels(n), count(n) ORDER BY count(n) DESC`

Expected: you see rows for Broker, Property, Tenant, Insight, Pursuit, Lease, Market, AssetClass, Community, etc. If the graph is empty, the backfill has not run yet.

### 2. Verify Node Counts (minimum thresholds for demo)

In Neo4j Browser, run:

```cypher
MATCH (n:Insight) RETURN count(n) AS insights
MATCH (n:Broker) RETURN count(n) AS brokers
MATCH (n:Property) RETURN count(n) AS properties
MATCH ()-[r:PREDICTED_AFFINITY]->() RETURN count(r) AS predicted_links
MATCH ()-[r:IN_COMMUNITY]->() RETURN count(r) AS community_edges
```

Minimum acceptable for a confident demo:
- Insights: 50+
- Brokers: 10+
- Properties: 50+
- PredictedLinks: 1+ (best-effort per PRD)
- CommunityEdges: 1+ (Louvain has run)

If any count is 0, do not proceed. See "Common Failure Modes" at the bottom.

### 3. Start the Always-On Ingester

In a dedicated terminal tab (leave this running throughout the demo):

```bash
cd $REPO_ROOT
python -m ingester.streaming
```

Expected log output within 10 seconds:
```
[ingester] Snowflake connection OK
[ingester] Neo4j connection OK
[ingester] Backfill complete: X brokers, Y properties, Z leases
[ingester] Stream poll started — interval 60s
```

If you see an authentication error, check SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD in your .env file.

### 4. Start the ML Refresh Process

In a second dedicated terminal tab:

```bash
cd $REPO_ROOT
python -m ml.refresh
```

Expected log output:
```
[ml.refresh] Node2Vec started: 128-dim, walkLength=80, walksPerNode=10
[ml.refresh] Node2Vec complete: X embeddings written
[ml.refresh] Louvain complete: Y communities detected
[ml.refresh] Link prediction complete: Z edges written (score >= 0.5)
[ml.refresh] Next run in 600s
```

Wait for at least one full ML refresh cycle to complete before running Q1/Q2/Q3 demo questions. This typically takes 1-3 minutes on a seeded graph.

### 5. Configure Claude Desktop

Ensure `~/Library/Application Support/Claude/claude_desktop_config.json` contains:

```json
{
  "mcpServers": {
    "cre-knowledge-graph": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "$REPO_ROOT",
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "<your-neo4j-password>"
      }
    }
  }
}
```

Then quit and relaunch Claude Desktop. Verify tools are available by typing:
```
Can you call health_check and tell me the graph status?
```

Expected: Claude returns a structured response with node counts and status "OK". If it says "no tools available", the config path is wrong or the server failed to start (see Common Failure Modes).

---

## Demo Script — The 3 Canonical Questions

Use these prompts VERBATIM. Do not paraphrase; the phrasing is tuned to trigger the correct tool.

---

### Q1 — Insight to Matching Properties and Brokers

**Prompt to paste into Claude Desktop:**
```
Based on insight INS-20260319-001 about Microsoft's Boston Office expansion, what are the matching properties and brokers I can reach out to?
```

**What a good response looks like:**
- Claude invokes `find_matching_properties_for_insight` with `insight_id="INS-20260319-001"`
- Response includes at least 3-5 Boston Office properties with addresses, scores, and reasons
- Each property lists 1+ brokers who have transacted on it
- Broker names are human-readable (e.g., "Jane Liu at CBRE"), not raw keys like "email::jane@cbre.com"
- Claude's narrative cites specific property names and broker names — not generic placeholders

**What "good" looks like (example response shape):**
```
Based on the Boston Office expansion insight, here are the top matching properties:

1. 200 State Street, Boston — Score: 0.87
   Reason: Class A Office in Downtown Boston submarket; PREDICTED_AFFINITY to expansion insight
   Broker: Jane Liu (CBRE) — $145M deal volume in Boston Office

2. 125 High Street, Boston — Score: 0.81
   ...

Recommended brokers for outreach:
- Jane Liu (CBRE): Active SPOC for Microsoft on TenantRep; top-quartile Boston Office volume
- Tom Patel (JLL): Louvain community match; 3 closed Office deals in Downtown Boston
```

---

### Q2 — Next Best Actions for a Deal

**Prompt to paste into Claude Desktop:**
```
Based on this deal in its current state, what actions can I take? The deal ID is [paste a real PURSUIT_ID from the graph].
```

To get a real PURSUIT_ID, run this in Neo4j Browser first:
```cypher
MATCH (p:Pursuit) RETURN p.pursuit_id, p.stage, p.client ORDER BY p.pursuit_id LIMIT 5
```

**What a good response looks like:**
- Claude invokes `suggest_next_best_actions_for_deal`
- Response references at least 1 historical comparable Pursuit by ID (e.g., "PUR-2025-142 which closed from Proposal Sent after a 2-week follow-up")
- Suggested actions are specific, not generic (e.g., "Loop in Tom Patel who closed a similar Chicago Office TenantRep in 2025")
- If fallback_used=true, Claude transparently says "No direct comparables found; recommending based on Boston Office community brokers"

---

### Q3 — Best Broker for a Deal

**Prompt to paste into Claude Desktop:**
```
Who is the best broker to work with me on this deal based on preferences? Deal details: San Francisco Office tenant representation, approximately 50,000 square feet.
```

**What a good response looks like:**
- Claude invokes `recommend_broker_for_deal` with market="San Francisco", asset_class="Office", service_line="TenantRep"
- Response ranks at least 2 named brokers (not synthetic keys)
- Each broker has a stated reason grounded in graph data (deal volume, SPOC status, community match)
- Expired SPOCs are labeled "expired" and ranked lower — not silently excluded
- Example: "Jane Liu ranks #1: Active SPOC for your account on TenantRep; $92M SF Office volume in past 12 months; in Louvain community #7 with 3 in-scope properties"

---

## Common Failure Modes

### Empty rankings / no properties returned

**Symptom:** Q1 or Q3 returns an empty list or "No properties found."
**Cause:** Embeddings not populated — Node2Vec has not run or failed.
**Diagnosis:** In Neo4j Browser: `MATCH (b:Broker) WHERE b.embedding IS NULL RETURN count(b)`
**Fix:** Check ml.refresh logs for errors. Restart: `python -m ml.refresh`
**Phase 3.5 note:** If the property name is wrong (e.g., stored as "vector" not "embedding"), the MCP ranker will silently fall back to structural queries and return lower-quality results.

### Tool not found in Claude Desktop

**Symptom:** Claude says "I don't have access to a tool called find_matching_properties_for_insight."
**Cause:** MCP server failed to register tools, or Claude Desktop config path is wrong.
**Diagnosis:** Check `~/Library/Application Support/Claude/claude_desktop_config.json` — verify the `cwd` and `command` paths are absolute and correct. Try running the server manually: `python -m mcp_server.server` and verify no import errors.
**Fix:** After fixing the config, fully quit Claude Desktop (Cmd+Q, not just close window) and relaunch.

### Neo4j unreachable / DEGRADED health_check

**Symptom:** health_check returns status "DEGRADED" with neo4j_reachable: false.
**Cause:** Docker container stopped or Neo4j not yet finished starting.
**Fix:** `docker compose ps` — verify neo4j container is "Up". If not: `docker compose restart neo4j` and wait 30 seconds.

### Ingester exiting immediately

**Symptom:** `python -m ingester.streaming` exits within 5 seconds.
**Cause:** Snowflake credentials wrong or Snowflake is unreachable.
**Diagnosis:** Check for "Authentication failed" or "Network timeout" in the exit log.
**Fix:** Verify .env values: SNOWFLAKE_ACCOUNT format is `orgname-accountname` (not just account name). SNOWFLAKE_ROLE must be ACCOUNTADMIN for HACKATHON.PUBLIC access.

### Broker names showing as "email::..." in response

**Symptom:** Claude says "Top broker: email::jane@cbre.com" instead of "Jane Liu."
**Cause:** Phase 3.5 fix not landed — the `name` property is stored under the merge key format.
**Diagnosis:** `MATCH (b:Broker) RETURN b.name LIMIT 5` in Neo4j Browser.
**Fix:** This is a Phase 3.5 fix. Do not demo until it lands.

### Freshness warning in health_check

**Symptom:** health_check returns ml_freshness_warning: true or latest_insight_age_minutes > 15.
**Cause:** Ingester or ML refresh process has stopped.
**Fix:** `docker compose restart ingester` or restart `python -m ml.refresh` in its terminal tab.

---

## Post-Demo Cleanup

```bash
docker compose down
# Optional: wipe Neo4j volume to reset for next run
docker compose down -v
```

To remove Snowflake streaming artifacts (Stream + Task):
```sql
DROP STREAM IF EXISTS HACKATHON.PUBLIC.CRE_INSIGHTS_STREAM;
DROP TASK IF EXISTS HACKATHON.PUBLIC.CRE_INSIGHTS_TASK;
```
