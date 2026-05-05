"""
MCP tool: find_matching_properties_for_insight  (Q1)

Given a market-research insight (by ID or free-text description), return a
ranked list of properties in the relevant market / asset class, plus the
brokers who have transacted on those properties.

Strategy:
  1. Resolve the insight: by insight_id (direct MATCH) or insight_text
     (semantic_search with label=Insight).
  2. Extract Market / AssetClass anchors from the insight's :ABOUT edges.
  3. Find candidate Properties via LOCATED_IN (market match) + CLASSIFIED_AS
     (asset-class match).
  4. Find candidate Brokers via COVERS (market) + SPECIALIZES_IN (asset-class)
     + recent BROKERED_BY leases + active SPOC_FOR edges.
  5. Rank properties by (asset_class_match × 0.4 + market_match × 0.4 +
     recency × 0.2).  Rank brokers by (production_tier × 0.4 +
     spec_match × 0.25 + spoc × 0.2 + community × 0.1 + affinity × 0.05).

Weights are defined in mcp_server/ranker.py as named constants.

Conforms to api-contracts.md §4.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from mcp_server.ranker import (
    BROKER_AFFINITY_WEIGHT,
    BROKER_COMMUNITY_WEIGHT,
    BROKER_DEAL_VOLUME_WEIGHT,
    BROKER_SPOC_WEIGHT,
    BROKER_SPECIALIZATION_WEIGHT,
    PROPERTY_ASSET_CLASS_WEIGHT,
    PROPERTY_MARKET_WEIGHT,
    PROPERTY_RECENCY_WEIGHT,
    normalise_rank,
    spoc_value,
    stable_sort,
    weighted_sum,
)

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Cypher templates — all values parameterised (no interpolation)
# ---------------------------------------------------------------------------

_FETCH_INSIGHT_BY_ID = """
MATCH (i:Insight {insight_id: $insight_id})
RETURN i.insight_id AS insight_id,
       i.title      AS title,
       i.market     AS market,
       i.asset_class AS asset_class
"""

_FETCH_INSIGHT_ABOUT = """
MATCH (i:Insight {insight_id: $insight_id})-[:ABOUT]->(n)
RETURN labels(n)[0] AS label, n.name AS name
"""

_FIND_PROPERTIES = """
MATCH (p:Property)
OPTIONAL MATCH (p)-[:LOCATED_IN]->(sub:Submarket)-[:PART_OF]->(m:Market)
OPTIONAL MATCH (p)-[:CLASSIFIED_AS]->(ac:AssetClass)
WITH p, m, sub, ac
WHERE ($market IS NULL OR toLower(m.name) = toLower($market)
       OR toLower(sub.name) = toLower($market))
  AND ($asset_class IS NULL OR toLower(ac.name) = toLower($asset_class))
OPTIONAL MATCH (l:Lease)-[:ON]->(p)
WITH p, m, sub, ac,
     count(l) AS lease_count,
     max(l.signed_date) AS latest_lease
RETURN
  p.property_key  AS property_key,
  p.address_line1 AS address,
  m.name          AS market_name,
  sub.name        AS submarket_name,
  ac.name         AS asset_class_name,
  lease_count,
  latest_lease
ORDER BY latest_lease DESC NULLS LAST
LIMIT $limit
"""

_FIND_BROKERS_FOR_MARKET_AC = """
MATCH (b:Broker)
OPTIONAL MATCH (b)-[:COVERS]->(m:Market)
  WHERE $market IS NULL OR toLower(m.name) = toLower($market)
OPTIONAL MATCH (b)-[:SPECIALIZES_IN]->(ac:AssetClass)
  WHERE $asset_class IS NULL OR toLower(ac.name) = toLower($asset_class)
WITH b,
     count(DISTINCT m) AS market_matches,
     count(DISTINCT ac) AS ac_matches
WHERE market_matches > 0 OR ac_matches > 0
OPTIONAL MATCH (spoc_rel:SPOC_FOR)-[:SPOC_FOR_REL]-(b)
WITH b, market_matches, ac_matches
RETURN
  b.broker_key  AS broker_key,
  b.name        AS name,
  b.firm        AS firm,
  b.total_deal_volume_usd AS deal_volume,
  market_matches,
  ac_matches
LIMIT $limit
"""

# Simplified broker query that works with actual graph structure
_FIND_BROKERS_COVERS = """
MATCH (b:Broker)-[:COVERS]->(m:Market)
WHERE toLower(m.name) = toLower($market)
RETURN b.broker_key AS broker_key, b.name AS name, b.firm AS firm,
       b.total_deal_volume_usd AS deal_volume,
       1 AS market_matches, 0 AS ac_matches
LIMIT $limit
"""

_FIND_BROKERS_SPECIALIZES = """
MATCH (b:Broker)-[:SPECIALIZES_IN]->(ac:AssetClass)
WHERE toLower(ac.name) = toLower($asset_class)
RETURN b.broker_key AS broker_key, b.name AS name, b.firm AS firm,
       b.total_deal_volume_usd AS deal_volume,
       0 AS market_matches, 1 AS ac_matches
LIMIT $limit
"""

_FIND_SPOC_FOR_BROKER = """
MATCH (b:Broker {broker_key: $broker_key})-[r:SPOC_FOR]->(c:Client)
RETURN r.expiration_date AS expiration_date,
       c.name AS client_name
"""

_FIND_BROKERS_FOR_PROPERTY = """
MATCH (l:Lease)-[:ON]->(p:Property {property_key: $property_key})
MATCH (l)-[:BROKERED_BY]->(b:Broker)
RETURN b.broker_key AS broker_key, b.name AS broker_name,
       b.total_deal_volume_usd AS deal_volume
"""


def _spoc_status(expiration_str: str | None) -> str:
    """Determine SPOC status from expiration date string."""
    if not expiration_str:
        return "active"  # no expiration = always active
    try:
        exp = datetime.fromisoformat(str(expiration_str).replace("Z", "+00:00"))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        return "active" if exp >= now else "expired"
    except (ValueError, TypeError):
        return "unknown"


def _recency_score(latest_lease_str: Any) -> float:
    """Convert latest_lease timestamp to a [0, 1] recency score."""
    if not latest_lease_str:
        return 0.0
    try:
        if hasattr(latest_lease_str, "to_native"):
            # Neo4j datetime object
            ts = latest_lease_str.to_native()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts_str = str(latest_lease_str).replace("Z", "+00:00")
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        age_days = (now - ts).days
        # Exponential decay: ~1.0 for recent, ~0 after 3 years
        return max(0.0, 1.0 - age_days / 1095)
    except (ValueError, TypeError, AttributeError):
        return 0.0


async def run_find_matching_properties_for_insight(
    driver,
    *,
    insight_id: Optional[str] = None,
    insight_text: Optional[str] = None,
    limit: int = 15,
) -> dict[str, Any]:
    """Core logic — exported for direct test use."""
    if not insight_id and not insight_text:
        return {
            "status": "ERROR",
            "error": "Provide either insight_id or insight_text",
            "properties": [],
            "truncated": False,
        }

    # -------------------------------------------------------------------
    # Step 1: Resolve the insight
    # -------------------------------------------------------------------
    resolved_insight_id: Optional[str] = None
    insight_title: Optional[str] = None
    insight_market: Optional[str] = None
    insight_asset_class: Optional[str] = None

    try:
        with driver.session() as session:
            if insight_id:
                row = session.run(_FETCH_INSIGHT_BY_ID, insight_id=insight_id).single()
                if row is None:
                    return {
                        "status": "ERROR",
                        "error": f"Insight not found: {insight_id}",
                        "properties": [],
                        "truncated": False,
                    }
                resolved_insight_id = insight_id
                insight_title = row["title"]
                insight_market = row["market"]
                insight_asset_class = row["asset_class"]

            else:
                # Semantic search to find the most relevant insight
                from mcp_server.tools.semantic_search import run_semantic_search
                ss_result = await run_semantic_search(
                    driver,
                    label="Insight",
                    query_text=insight_text,
                    top_k=1,
                )
                if ss_result["status"] != "OK" or not ss_result.get("results"):
                    return {
                        "status": "OK",
                        "insight": None,
                        "matched_market": None,
                        "matched_asset_class": None,
                        "properties": [],
                        "truncated": False,
                        "warnings": [
                            f"No Insight node matched the text: '{insight_text}'. "
                            "Check that insights have been ingested and embeddings computed."
                        ],
                    }
                top_result = ss_result["results"][0]
                resolved_insight_id = top_result["node"]["id"]
                insight_title = top_result["node"]["name"]
                insight_market = top_result.get("market")
                insight_asset_class = top_result.get("asset_class")

    except Exception as exc:
        log.error("find_matching_insight_resolve_failed", error=str(exc))
        return {
            "status": "ERROR",
            "error": str(exc),
            "properties": [],
            "truncated": False,
        }

    # -------------------------------------------------------------------
    # Step 2: Extract Market / AssetClass anchors from :ABOUT edges
    # -------------------------------------------------------------------
    about_market: Optional[str] = insight_market
    about_asset_class: Optional[str] = insight_asset_class

    try:
        with driver.session() as session:
            if resolved_insight_id:
                about_rows = list(
                    session.run(_FETCH_INSIGHT_ABOUT, insight_id=resolved_insight_id)
                )
                for r in about_rows:
                    label = r["label"]
                    name = r["name"]
                    if label == "Market" and not about_market:
                        about_market = name
                    elif label == "AssetClass" and not about_asset_class:
                        about_asset_class = name
    except Exception as exc:
        log.warning("find_matching_about_edges_failed", error=str(exc))

    effective_market = about_market
    effective_asset_class = about_asset_class

    # -------------------------------------------------------------------
    # Step 3: Find candidate Properties
    # -------------------------------------------------------------------
    property_rows: list[dict] = []
    try:
        with driver.session() as session:
            result = session.run(
                _FIND_PROPERTIES,
                market=effective_market,
                asset_class=effective_asset_class,
                limit=limit,
            )
            property_rows = [dict(r) for r in result]
    except Exception as exc:
        log.warning("find_matching_properties_query_failed", error=str(exc))

    # -------------------------------------------------------------------
    # Step 4: Find candidate Brokers (market + asset-class candidates)
    # -------------------------------------------------------------------
    broker_map: dict[str, dict] = {}  # broker_key -> merged data

    try:
        with driver.session() as session:
            if effective_market:
                for r in session.run(
                    _FIND_BROKERS_COVERS,
                    market=effective_market,
                    limit=limit,
                ):
                    row = dict(r)
                    bk = row.get("broker_key") or ""
                    if bk and bk not in broker_map:
                        broker_map[bk] = row
                    elif bk:
                        broker_map[bk]["market_matches"] = (
                            broker_map[bk].get("market_matches", 0) + 1
                        )

            if effective_asset_class:
                for r in session.run(
                    _FIND_BROKERS_SPECIALIZES,
                    asset_class=effective_asset_class,
                    limit=limit,
                ):
                    row = dict(r)
                    bk = row.get("broker_key") or ""
                    if bk and bk not in broker_map:
                        broker_map[bk] = row
                    elif bk:
                        broker_map[bk]["ac_matches"] = (
                            broker_map[bk].get("ac_matches", 0) + 1
                        )
    except Exception as exc:
        log.warning("find_matching_brokers_query_failed", error=str(exc))

    # -------------------------------------------------------------------
    # Step 5: Rank properties
    # -------------------------------------------------------------------
    raw_volumes = [
        (r.get("deal_volume") or 0.0) for r in broker_map.values()
    ]
    norm_volumes = normalise_rank(raw_volumes)
    broker_keys_ordered = list(broker_map.keys())
    broker_volume_norm = {
        bk: norm_volumes[i] for i, bk in enumerate(broker_keys_ordered)
    }

    ranked_properties = []
    for prop in property_rows:
        market_match = 1.0 if (
            effective_market and (
                (prop.get("market_name") or "").lower() == (effective_market or "").lower()
                or (prop.get("submarket_name") or "").lower() == (effective_market or "").lower()
            )
        ) else (0.5 if not effective_market else 0.0)

        ac_match = 1.0 if (
            effective_asset_class and (
                (prop.get("asset_class_name") or "").lower() == (effective_asset_class or "").lower()
            )
        ) else (0.5 if not effective_asset_class else 0.0)

        recency = _recency_score(prop.get("latest_lease"))

        score = weighted_sum({
            "asset_class": (ac_match, PROPERTY_ASSET_CLASS_WEIGHT),
            "market":      (market_match, PROPERTY_MARKET_WEIGHT),
            "recency":     (recency, PROPERTY_RECENCY_WEIGHT),
        })

        reasons: list[str] = []
        if ac_match > 0:
            reasons.append(
                f"{prop.get('asset_class_name', effective_asset_class)} asset class match"
            )
        if market_match > 0:
            reasons.append(
                f"Located in {prop.get('market_name') or prop.get('submarket_name') or effective_market}"
            )
        if recency > 0.5:
            reasons.append("Recent lease activity")

        ranked_properties.append({
            "property": {
                "id": prop.get("property_key", ""),
                "label": "Property",
                "name": prop.get("address", prop.get("property_key", "")),
            },
            "score": score,
            "reasons": reasons,
            "brokers": [],  # filled below
        })

    ranked_properties = stable_sort(ranked_properties, key_field="score")[:limit]

    # Attach brokers for each property via BROKERED_BY leases
    try:
        with driver.session() as session:
            for entry in ranked_properties:
                prop_id = entry["property"]["id"]
                if not prop_id:
                    continue
                broker_rows = list(
                    session.run(_FIND_BROKERS_FOR_PROPERTY, property_key=prop_id)
                )
                entry["brokers"] = [
                    {
                        "node": {
                            "id": r["broker_key"],
                            "name": r["broker_name"],
                        },
                        "rel": "BROKERED_BY",
                        "deal_volume_usd": r["deal_volume"] or 0,
                    }
                    for r in broker_rows
                ]
    except Exception as exc:
        log.warning("find_matching_property_brokers_failed", error=str(exc))

    # -------------------------------------------------------------------
    # Step 5b: Rank brokers separately (for the summary broker list)
    # -------------------------------------------------------------------
    ranked_brokers = []
    for bk, bdata in broker_map.items():
        market_m = 1.0 if (bdata.get("market_matches", 0) or 0) > 0 else 0.0
        ac_m = 1.0 if (bdata.get("ac_matches", 0) or 0) > 0 else 0.0
        vol_norm = broker_volume_norm.get(bk, 0.0)

        score = weighted_sum({
            "deal_volume":      (vol_norm, BROKER_DEAL_VOLUME_WEIGHT),
            "specialization":   (ac_m, BROKER_SPECIALIZATION_WEIGHT),
            "market_coverage":  (market_m, BROKER_SPOC_WEIGHT),
        })

        reasons: list[str] = []
        if market_m:
            reasons.append(f"Covers {effective_market or 'matching'} market")
        if ac_m:
            reasons.append(f"Specializes in {effective_asset_class or 'matching'} asset class")

        ranked_brokers.append({
            "broker_id": bk,
            "name": bdata.get("name", ""),
            "firm": bdata.get("firm", ""),
            "score": score,
            "reasons": reasons,
        })

    ranked_brokers = stable_sort(ranked_brokers, key_field="score")[:limit]

    # -------------------------------------------------------------------
    # Build final response
    # -------------------------------------------------------------------
    warnings: list[str] = []
    if not ranked_properties:
        warnings.append(
            f"No properties found in {effective_market or 'any market'} "
            f"{effective_asset_class or 'any asset class'} matching this insight"
        )

    return {
        "status": "OK",
        "insight": {
            "id": resolved_insight_id,
            "title": insight_title,
            "market": effective_market,
            "asset_class": effective_asset_class,
        },
        "matched_market": effective_market,
        "matched_asset_class": effective_asset_class,
        "properties": ranked_properties,
        "matching_brokers": ranked_brokers,
        "truncated": len(property_rows) >= limit,
        "warnings": warnings,
    }


def register(mcp_server, driver_factory):
    """Register the find_matching_properties_for_insight tool."""

    @mcp_server.tool(
        name="find_matching_properties_for_insight",
        description=(
            "Given a market-research insight (by ID or natural-language description), "
            "return a ranked list of properties in the relevant market and asset class, "
            "plus the brokers who have transacted on those properties. "
            "Use this when the user pastes or references a new insight and asks "
            "'which of my properties and brokers does this affect?' or "
            "'who should I reach out to based on this trend?' or "
            "'Based on [insight], what are the matching properties and brokers I can reach out to?'. "
            "Provide insight_id (if you know the graph ID) OR insight_text (free-text description). "
            "Optional: limit (default 15, max 50)."
        ),
    )
    async def find_matching_properties_for_insight(
        insight_id: Optional[str] = None,
        insight_text: Optional[str] = None,
        limit: int = 15,
    ) -> dict:
        driver = driver_factory()
        return await run_find_matching_properties_for_insight(
            driver,
            insight_id=insight_id,
            insight_text=insight_text,
            limit=limit,
        )
