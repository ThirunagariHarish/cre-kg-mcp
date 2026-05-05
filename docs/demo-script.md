# CRE Knowledge Graph MCP — Demo Script

Phase 4 demo guide for hackathon judges. Mirrors `scripts/demo.sh` and README §4 sample prompts exactly.

---

## Pre-flight

Run these steps in order before opening Claude Desktop.

```bash
# 1. Start Neo4j + GDS
docker compose up -d

# 2. Verify Neo4j is healthy (should show "healthy")
docker compose ps

# 3. Run backfill if graph is empty
python scripts/backfill.py

# 4. Start streaming ingester (separate terminal)
python -m ingester.streaming

# 5. Start ML refresh worker (separate terminal)
python -m ml.refresh

# 6. Run demo.sh to poll until enrichments are ready
bash scripts/demo.sh
```

Expected counts when ready:

| Metric | Minimum |
|---|---|
| Insights | 50+ |
| Broker embeddings | >0 |
| Broker community_id | >0 |
| PredictedLinks | >0 |

Verify in Neo4j Browser at http://localhost:7474:

```cypher
MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt ORDER BY cnt DESC
```

---

## The 3 Canonical Questions

### Q1 — Find matching properties and brokers from a market insight

**Verbatim Claude prompt:**

```
Based on the latest Dallas Industrial absorption insight, what are the matching properties and brokers I can reach out to?
```

**Tool invoked:** `find_matching_properties_for_insight`

**Expected response shape:**

```json
{
  "status": "OK",
  "insight": { "id": "...", "title": "DFW Industrial absorption surge ..." },
  "matched_market": "dallas-fort worth",
  "matched_asset_class": "industrial",
  "properties": [
    {
      "property": { "id": "...", "name": "..." },
      "score": 0.84,
      "reasons": ["Industrial asset class match", "Located in dallas-fort worth", "Recent lease activity"],
      "brokers": [{ "node": {"id": "...", "name": "..."}, "rel": "BROKERED_BY", "deal_volume_usd": 145000000 }]
    }
  ],
  "matching_brokers": [
    { "broker_id": "...", "name": "...", "firm": "...", "score": 0.88, "reasons": ["Covers dallas-fort worth market", "Specializes in industrial asset class"] }
  ],
  "truncated": false
}
```

**What "good" looks like:**
- At least 3 properties returned with non-zero scores.
- `matching_brokers` list non-empty with scores that vary (not all the same value).
- `reasons` mention recency or community.
- `matched_market` = `"dallas-fort worth"`, `matched_asset_class` = `"industrial"`.

**Failure fallback:** If properties list is empty, the graph may not have DFW Industrial properties. Ask Claude: "Run a health check on the CRE graph" — if `node_counts.Property` is 0, re-run `python scripts/backfill.py`. If embeddings are missing, re-run `python -m ml.refresh --once`.

---

### Q2 — Next best actions on a stalled deal

**Verbatim Claude prompt:**

```
Based on my deal PUR-001 in its current state, what actions can I take?
```

**Tool invoked:** `suggest_next_best_actions_for_deal`

**Expected response shape:**

```json
{
  "status": "OK",
  "pursuit": { "id": "PUR-001", "stage": "Proposal Sent", "client": "Acme Corp" },
  "comparables": [
    {
      "pursuit": { "id": "PUR-200", "stage": "Closed Won", "outcome": "Closed Won" },
      "similarity_score": 0.80,
      "closing_broker": { "id": "email::...", "name": "Tom Patel" },
      "service_line": "tenantrep"
    }
  ],
  "suggested_actions": [
    "Schedule follow-up with primary client contact (N/M similar pursuits advanced after follow-up)",
    "Loop in <broker> — closed similar deal in same market"
  ],
  "fallback_used": false,
  "truncated": false
}
```

**What "good" looks like:**
- `comparables` contains won pursuits only (outcome = "Closed Won" or "Won").
- `similarity_score` values vary across comparables (not all 0.75).
- `suggested_actions` reference the comparable brokers by name.
- `fallback_used: false` when comparables exist.

**Failure fallback:** If `fallback_used: true`, the graph has no won pursuits matching PUR-001's market/asset class. Ask Claude to run `health_check` and check `node_counts.Pursuit`. If zero, re-run backfill.

---

### Q3 — Best broker recommendation for a deal

**Verbatim Claude prompt:**

```
Who is the best broker to work with me on an Industrial deal in Dallas for tenant representation?
```

**Tool invoked:** `recommend_broker_for_deal`

**Expected response shape:**

```json
{
  "status": "OK",
  "deal_context": { "market": "dallas", "asset_class": "industrial", "service_line": "tenantrep" },
  "brokers": [
    {
      "broker": { "id": "email::...", "name": "Jane Liu", "firm": "CBRE", "community_id": 7 },
      "score": 0.88,
      "components": {
        "deal_volume_score": 0.92,
        "production_tier": "top-quartile",
        "specialization_match": true,
        "market_coverage_match": true,
        "spoc_status": "none",
        "community_match": false,
        "community_overlap_with_me": false,
        "predicted_affinity_score": 0.00
      },
      "reasons": ["Covers dallas market", "Specializes in industrial"]
    }
  ],
  "truncated": false
}
```

**What "good" looks like:**
- At least 5 brokers returned (or fewer if data is sparse — check `truncated`).
- Top-ranked broker has a higher `deal_volume_score` than the bottom-ranked broker.
- `community_match` / `community_overlap_with_me` populated as `true`/`false` (not null).
- `production_tier` populated on every broker entry.

**Failure fallback:** If `brokers` is empty, Dallas Industrial brokers may not have loaded. Check `node_counts.Broker` via `health_check`. If below 100, re-run `python scripts/backfill.py`. If `deal_volume_score` is uniformly 1.0 for all brokers, deal_volume_usd may not be populated — verify ingester loaded `CRE_BROKERS.YTD_DEAL_VOLUME`.

---

## Verification Checklist

- [ ] `health_check` returns `neo4j_reachable: true`, non-null `last_ml_run_at`, `ml_freshness_warning: false`
- [ ] Q1 returns ≥3 properties with non-uniform scores
- [ ] Q1 `matching_brokers` list non-empty with reason strings
- [ ] Q2 comparables have non-uniform `similarity_score` values
- [ ] Q2 comparables show `outcome: "Closed Won"` or `"Won"` (not lost/prospecting pursuits)
- [ ] Q3 returns ≥5 brokers with top broker having higher `deal_volume_score` than bottom
- [ ] Q3 `production_tier` populated on every broker
