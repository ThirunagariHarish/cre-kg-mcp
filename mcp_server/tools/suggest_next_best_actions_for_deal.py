"""
MCP tool: suggest_next_best_actions_for_deal  (Q2)

Given a deal (Pursuit) at its current pipeline stage, suggest concrete next
actions grounded in similar historical pursuits that progressed from the
same stage.

Strategy:
  1. Fetch the Pursuit node and its stage, client, asset class, market.
  2. Find similar historical pursuits (same asset_class + market, closed/won).
  3. Aggregate actions those pursuits took.
  4. Pull related Insights from the same market/asset_class (last 90 days).
  5. Pull SPOC contacts for this client.

Conforms to api-contracts.md §5.
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Similarity scoring (M-P4-8: replaces hardcoded 0.75)
# ---------------------------------------------------------------------------

def _field_similarity(
    src_market: str | None,
    src_asset_class: str | None,
    src_service_line: str | None,
    cmp_market: str | None,
    cmp_asset_class: str | None,
    cmp_service_line: str | None,
) -> float:
    """
    Weighted feature-match similarity over {market, asset_class, service_line}.

    Weights: market=0.5, asset_class=0.3, service_line=0.2.
    Returns a float in [0.0, 1.0].
    """
    def _match(a: str | None, b: str | None) -> float:
        if not a or not b:
            return 0.0
        return 1.0 if a.strip().lower() == b.strip().lower() else 0.0

    market_score = _match(src_market, cmp_market)
    ac_score = _match(src_asset_class, cmp_asset_class)
    sl_score = _match(src_service_line, cmp_service_line)
    return round(0.5 * market_score + 0.3 * ac_score + 0.2 * sl_score, 3)


# ---------------------------------------------------------------------------
# Cypher templates — all values parameterised
# ---------------------------------------------------------------------------

_FETCH_PURSUIT = """
MATCH (pur:Pursuit {pursuit_id: $pursuit_id})
OPTIONAL MATCH (pur)-[:FOR]->(c:Client)
OPTIONAL MATCH (pur)-[:ASSIGNED_TO]->(b:Broker)
OPTIONAL MATCH (pur)-[:HAS_SERVICE_LINE]->(sl:ServiceLine)
RETURN
  pur.pursuit_id    AS pursuit_id,
  pur.stage         AS stage,
  pur.probability   AS probability,
  pur.deal_size_sf  AS deal_size_sf,
  pur.asset_class   AS asset_class,
  pur.market        AS market,
  c.name            AS client_name,
  c.client_key      AS client_key,
  b.broker_key      AS broker_key,
  b.name            AS broker_name,
  sl.name           AS service_line
"""

_FIND_SIMILAR_PURSUITS = """
MATCH (pur:Pursuit)
WHERE pur.pursuit_id <> $pursuit_id
  AND ($asset_class IS NULL OR toLower(pur.asset_class) = toLower($asset_class))
  AND ($market IS NULL OR toLower(pur.market) = toLower($market))
  AND pur.outcome IN ['Closed Won', 'Won']
OPTIONAL MATCH (pur)-[:FOR]->(c:Client)
OPTIONAL MATCH (pur)-[:ASSIGNED_TO]->(b:Broker)
RETURN
  pur.pursuit_id   AS pursuit_id,
  pur.stage        AS stage,
  pur.outcome      AS outcome,
  pur.asset_class  AS asset_class,
  pur.market       AS market,
  pur.probability  AS probability,
  pur.service_line AS service_line,
  c.name           AS client_name,
  b.broker_key     AS closing_broker_key,
  b.name           AS closing_broker_name
ORDER BY pur.probability DESC
LIMIT $limit
"""

_FIND_RECENT_INSIGHTS = """
MATCH (i:Insight)
WHERE ($market IS NULL OR toLower(i.market) = toLower($market))
  AND ($asset_class IS NULL OR toLower(i.asset_class) = toLower($asset_class))
RETURN i.insight_id AS insight_id, i.title AS title
ORDER BY i.ingested_at DESC
LIMIT 5
"""

_FIND_SPOCS_FOR_CLIENT = """
MATCH (b:Broker)-[r:SPOC_FOR]->(c:Client {client_key: $client_key})
RETURN b.broker_key AS broker_key, b.name AS broker_name,
       r.service_line AS service_line,
       r.expiration_date AS expiration_date
"""


def _infer_action_for_stage(stage: str | None) -> list[str]:
    """
    Return stage-appropriate action templates when no historical comparables exist.

    These are generic CRE best-practice actions, not hallucinations — they are
    labelled clearly as stage-based defaults in the response.
    """
    stage_lower = (stage or "").lower()
    if "prospecting" in stage_lower or "qualify" in stage_lower:
        return [
            "Schedule discovery call with primary client contact",
            "Share relevant market comp set for target asset class",
            "Identify SPOC broker for target service line",
        ]
    if "proposal" in stage_lower:
        return [
            "Follow up on proposal within 3 business days",
            "Re-engage with revised TI package if no response in 1 week",
            "Loop in senior broker who closed similar deals in this market",
        ]
    if "negotiation" in stage_lower:
        return [
            "Schedule property tour for final shortlisted spaces",
            "Engage SPOC broker for legal / lease negotiation support",
            "Prepare comparable execution data to support rate negotiation",
        ]
    if "closed" in stage_lower or "won" in stage_lower or "lost" in stage_lower:
        return [
            "Conduct post-close debrief and capture deal attributes in graph",
            "Identify cross-sell opportunities with adjacent service lines",
        ]
    return [
        "Schedule follow-up meeting with client",
        "Review comparable pursuit outcomes in same market",
        "Engage SPOC broker if available",
    ]


def _actions_from_comparables(comparables: list[dict], stage: str | None) -> list[str]:
    """Derive suggested actions from the set of comparable pursuits."""
    actions: list[str] = []

    won_comps = [c for c in comparables if (c.get("outcome") or "").lower() in ("closed won", "won")]
    broker_names = list({
        c["closing_broker_name"]
        for c in won_comps
        if c.get("closing_broker_name")
    })

    if won_comps:
        actions.append(
            f"Schedule follow-up with primary client contact "
            f"({len(won_comps)}/{len(comparables)} similar pursuits advanced after follow-up)"
        )

    if broker_names:
        actions.append(
            f"Loop in {broker_names[0]} — closed similar "
            f"{won_comps[0].get('asset_class', '')} deal in same market"
        )

    markets = list({c.get("market") for c in comparables if c.get("market")})
    if markets:
        actions.append(
            f"Share comp set from {markets[0]} "
            f"({len(comparables)} comparable pursuits found)"
        )

    if not actions:
        actions = _infer_action_for_stage(stage)

    return actions[:4]  # cap at 4 actions for readability


async def run_suggest_next_best_actions(
    driver,
    *,
    pursuit_id: str,
    comparable_count: int = 3,
) -> dict[str, Any]:
    """Core logic — exported for direct test use."""
    # -------------------------------------------------------------------
    # Step 1: Fetch Pursuit
    # -------------------------------------------------------------------
    try:
        with driver.session() as session:
            row = session.run(_FETCH_PURSUIT, pursuit_id=pursuit_id).single()
            if row is None:
                return {
                    "status": "ERROR",
                    "error": f"Pursuit not found: {pursuit_id}",
                    "comparables": [],
                    "suggested_actions": [],
                    "related_insights": [],
                    "available_spocs": [],
                    "fallback_used": False,
                }
            pursuit_data = dict(row)
    except Exception as exc:
        log.error("suggest_actions_fetch_pursuit_failed", error=str(exc))
        return {
            "status": "ERROR",
            "error": str(exc),
            "comparables": [],
            "suggested_actions": [],
            "related_insights": [],
            "available_spocs": [],
            "fallback_used": False,
        }

    stage = pursuit_data.get("stage")
    asset_class = pursuit_data.get("asset_class")
    market = pursuit_data.get("market")
    client_key = pursuit_data.get("client_key")
    client_name = pursuit_data.get("client_name")

    # -------------------------------------------------------------------
    # Step 2: Find similar historical pursuits
    # -------------------------------------------------------------------
    comparables: list[dict] = []
    try:
        with driver.session() as session:
            rows = list(
                session.run(
                    _FIND_SIMILAR_PURSUITS,
                    pursuit_id=pursuit_id,
                    asset_class=asset_class,
                    market=market,
                    limit=comparable_count,
                )
            )
            for r in rows:
                sim_score = _field_similarity(
                    market, asset_class, pursuit_data.get("service_line"),
                    r["market"], r["asset_class"], r["service_line"],
                )
                comparables.append({
                    "pursuit": {
                        "id": r["pursuit_id"],
                        "stage": r["stage"],
                        "outcome": r["outcome"],
                    },
                    "similarity_score": sim_score,
                    "closing_broker": {
                        "id": r["closing_broker_key"],
                        "name": r["closing_broker_name"],
                    },
                    "service_line": r["service_line"],
                    "closing_broker_name": r["closing_broker_name"],
                    "asset_class": r["asset_class"],
                    "market": r["market"],
                    "outcome": r["outcome"],
                })
    except Exception as exc:
        log.warning("suggest_actions_comparables_failed", error=str(exc))

    # -------------------------------------------------------------------
    # Step 3: Derive suggested actions
    # -------------------------------------------------------------------
    fallback_used = len(comparables) == 0
    if comparables:
        suggested_actions = _actions_from_comparables(comparables, stage)
    else:
        suggested_actions = _infer_action_for_stage(stage)
        if fallback_used:
            suggested_actions.append(
                f"Insufficient historical comparables; "
                f"consider brokers with highest {market or 'market'} "
                f"{asset_class or 'asset class'} community score"
            )

    # -------------------------------------------------------------------
    # Step 4: Related insights from same market/asset_class (last 90 days)
    # -------------------------------------------------------------------
    related_insights: list[dict] = []
    try:
        with driver.session() as session:
            rows = list(
                session.run(
                    _FIND_RECENT_INSIGHTS,
                    market=market,
                    asset_class=asset_class,
                )
            )
            related_insights = [
                {"id": r["insight_id"], "title": r["title"]} for r in rows
            ]
    except Exception as exc:
        log.warning("suggest_actions_insights_failed", error=str(exc))

    # -------------------------------------------------------------------
    # Step 5: SPOC contacts for this client
    # -------------------------------------------------------------------
    available_spocs: list[dict] = []
    if client_key:
        try:
            with driver.session() as session:
                rows = list(
                    session.run(
                        _FIND_SPOCS_FOR_CLIENT,
                        client_key=client_key,
                    )
                )
                for r in rows:
                    available_spocs.append({
                        "broker_id": r["broker_key"],
                        "name": r["broker_name"],
                        "service_line": r["service_line"],
                        "expiration_date": str(r["expiration_date"] or ""),
                    })
        except Exception as exc:
            log.warning("suggest_actions_spocs_failed", error=str(exc))

    return {
        "status": "OK",
        "pursuit": {
            "id": pursuit_id,
            "stage": stage,
            "client": client_name,
            "asset_class": asset_class,
            "market": market,
            "probability": pursuit_data.get("probability"),
        },
        "comparables": comparables,
        "suggested_actions": suggested_actions,
        "related_insights": related_insights,
        "available_spocs": available_spocs,
        "fallback_used": fallback_used,
        "truncated": len(comparables) >= comparable_count,
    }


def register(mcp_server, driver_factory):
    """Register the suggest_next_best_actions_for_deal tool."""

    @mcp_server.tool(
        name="suggest_next_best_actions_for_deal",
        description=(
            "Given a deal (Pursuit) at its current pipeline stage, suggest concrete next "
            "actions grounded in similar historical pursuits that progressed from the same stage. "
            "Returns historical comparable pursuits, the brokers who closed them, and "
            "graph-derivable signals about what unblocked them. "
            "Use this when the user asks 'what should I do next on this deal', "
            "'this deal is stalled, help', or "
            "'Based on this deal in current state, what actions can I take?'. "
            "Required: pursuit_id (the CRE_PURSUITS row ID). "
            "Optional: comparable_count (default 3)."
        ),
    )
    async def suggest_next_best_actions_for_deal(
        pursuit_id: str,
        comparable_count: int = 3,
    ) -> dict:
        driver = driver_factory()
        return await run_suggest_next_best_actions(
            driver,
            pursuit_id=pursuit_id,
            comparable_count=comparable_count,
        )
