# CRE Knowledge Graph — E2E Test Suite

This directory contains the E2E test scaffolds for the CRE Knowledge Graph MCP server.

**Status:** Scaffold only — DO NOT RUN until Phase 4 + Phase 3.5 + Phase 4.5 fixes have all landed. See the runbook for the execution protocol.

---

## File Map

| File | What it covers | PRD stories |
|---|---|---|
| `conftest.py` | Fixtures: mcp_client, live_neo4j, seeded_graph, demo_data | All |
| `test_q1_insight_to_matches.py` | Q1: find_matching_properties_for_insight | STORY-4.1 |
| `test_q2_next_best_actions.py` | Q2: suggest_next_best_actions_for_deal | STORY-4.2 |
| `test_q3_broker_recommendation.py` | Q3: recommend_broker_for_deal | STORY-4.3 |
| `test_freshness_slo.py` | 15-minute streaming freshness SLO | STORY-2.1, STORY-2.2, PRD NFR |
| `test_ml_freshness.py` | ML enrichment freshness, embeddings, communities, link prediction | STORY-3.1, STORY-3.2, STORY-3.3 |
| `runbook.md` | Manual demo runbook for the presenter | STORY-5.2 |
| `README.md` | This file | — |

---

## Environment Variables

Copy `.env.example` to `.env` and fill in:

```
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<your-neo4j-password>

SNOWFLAKE_ACCOUNT=<orgname-accountname>
SNOWFLAKE_USER=<username>
SNOWFLAKE_PASSWORD=<password>
SNOWFLAKE_ROLE=ACCOUNTADMIN
SNOWFLAKE_DATABASE=HACKATHON
SNOWFLAKE_SCHEMA=PUBLIC

# Optional override — defaults to "python -m mcp_server.server"
MCP_SERVER_COMMAND=python -m mcp_server.server
```

---

## How to Run

### Install dependencies

```bash
# TODO: add to pyproject.toml when Phase 4 lands:
# pytest>=8.2, pytest-asyncio>=0.23, mcp>=1.0, neo4j>=5.19,
# snowflake-connector-python>=3.10

pip install pytest pytest-asyncio mcp neo4j snowflake-connector-python
```

### Run the fast suite (skips slow freshness test)

```bash
cd $REPO_ROOT
pytest tests/e2e/ -m "not slow" -v
```

### Run the full suite including the 15-minute freshness SLO test

```bash
pytest tests/e2e/ -v
# Or explicitly include slow:
pytest tests/e2e/ -m slow -v --timeout=1200
```

### Run a single file

```bash
pytest tests/e2e/test_q1_insight_to_matches.py -v
pytest tests/e2e/test_ml_freshness.py -v
```

### Run with Neo4j skip (dry-run schema checks only)

If Neo4j is not running, fixtures auto-skip with a clear reason. No manual skip flags needed.

---

## Test Markers

| Marker | Meaning | CI behavior |
|---|---|---|
| `@pytest.mark.slow` | Test takes >5 min (freshness SLO test) | Skipped by default in CI; run with `-m slow` explicitly |
| `@pytest.mark.asyncio` | Async test using pytest-asyncio | Requires `asyncio_mode = "auto"` in pytest.ini / pyproject |

Add to your `pyproject.toml` (TODO — Phase 4 owns pyproject):
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [
    "slow: tests that take > 5 minutes (freshness SLO)",
]
```

---

## Skip vs Fail Policy

- **Skips** are used only when the prerequisite infrastructure is not yet available (Neo4j not running, graph not seeded, Phase 4 not wired). A skip is not a test pass — it must be re-run after the infrastructure lands.
- **Failures** are genuine bugs. No test is marked skip to hide a failure (per QA hard rules).
- The `mcp_client` fixture itself skips if the MCP server exits immediately, which is expected until Phase 4 is wired.

---

## Dependency on Phase Completion

| Test file | Requires |
|---|---|
| `test_ml_freshness.py` | Phase 3.5 fixes (embedding property name), Phase 3 complete |
| `test_q1_insight_to_matches.py` | Phase 4 tool `find_matching_properties_for_insight` wired |
| `test_q2_next_best_actions.py` | Phase 4 tool `suggest_next_best_actions_for_deal` wired |
| `test_q3_broker_recommendation.py` | Phase 4 tool `recommend_broker_for_deal` wired |
| `test_freshness_slo.py` | Phase 2 (streaming) complete, Snowflake env vars set |
| `conftest.py` `seeded_graph` | Phase 1 backfill complete (50+ Insights, 10+ Brokers, 50+ Properties) |
