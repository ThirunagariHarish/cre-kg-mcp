"""
MCP tool: recommend_broker_for_deal  (Q3)

Recommend the best-fit broker(s) for a deal given its market, asset class,
and service line.  Ranks by:
  - Deal volume in market (production tier) — weight 0.40
  - Asset-class specialization match — weight 0.25
  - Active SPOC assignment for the client — weight 0.20 (0.5 for expired)
  - Graph community alignment — weight 0.10
  - PREDICTED_AFFINITY link score — weight 0.05

Expired SPOCs are included and flagged, never silently dropped.

Conforms to api-contracts.md §6.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from mcp_server.ranker import (
    BROKER_AFFINITY_WEIGHT,
    BROKER_COMMUNITY_WEIGHT,
    BROKER_DEAL_VOLUME_WEIGHT,
    BROKER_SPECIALIZATION_WEIGHT,
    BROKER_SPOC_WEIGHT,
    normalise_rank,
    spoc_value,
    stable_sort,
    weighted_sum,
)

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Cypher templates — all values parameterised
# ---------------------------------------------------------------------------

_FIND_BROKERS_MARKET = """
MATCH (b:Broker)-[:COVERS]->(m:Market)
WHERE toLower(m.name) = toLower($market)
RETURN b.broker_key AS broker_key, b.name AS name, b.firm AS firm,
       b.total_deal_volume_usd AS deal_volume,
       b.community_id AS community_id,
       1 AS market_match
"""

_FIND_BROKERS_ASSET_CLASS = """
MATCH (b:Broker)-[:SPECIALIZES_IN]->(ac:AssetClass)
WHERE toLower(ac.name) = toLower($asset_class)
RETURN b.broker_key AS broker_key, b.name AS name, b.firm AS firm,
       b.total_deal_volume_usd AS deal_volume,
       b.community_id AS community_id,
       1 AS ac_match
"""

_FIND_SPOC_FOR_BROKER = """
MATCH (b:Broker {broker_key: $broker_key})-[r:SPOC_FOR]->(c:Client)
WHERE $client_name IS NULL OR toLower(c.name) = toLower($client_name)
RETURN c.name AS client_name,
       r.service_line AS service_line,
       r.expiration_date AS expiration_date
"""

_FIND_AFFINITY = """
MATCH (pl:PredictedLink {from_id: $broker_key})
WHERE pl.to_label = 'Property' OR pl.to_label = 'Tenant'
RETURN max(pl.score) AS max_score
"""

_MY_BROKER_COMMUNITY = """
MATCH (b:Broker {broker_key: $broker_key})
RETURN b.community_id AS community_id
"""


def _spoc_status_from_expiry(expiration_str: Any) -> str:
    """Convert expiration date to 'active' | 'expired' | 'unknown'."""
    if not expiration_str:
        return "active"
    try:
        exp_str = str(expiration_str).replace("Z", "+00:00")
        exp = datetime.fromisoformat(exp_str)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        return "active" if exp >= now else "expired"
    except (ValueError, TypeError):
        return "unknown"


async def run_recommend_broker_for_deal(
    driver,
    *,
    market: str,
    asset_class: str,
    service_line: str,
    client_name: Optional[str] = None,
    my_broker_key: Optional[str] = None,
    k: int = 5,
) -> dict[str, Any]:
    """Core logic — exported for direct test use."""
    # -------------------------------------------------------------------
    # Step 1: Collect broker candidates from market + asset-class queries
    # -------------------------------------------------------------------
    broker_map: dict[str, dict] = {}  # broker_key -> merged candidate data

    try:
        with driver.session() as session:
            # Market-coverage candidates
            for r in session.run(_FIND_BROKERS_MARKET, market=market):
                row = dict(r)
                bk = row.get("broker_key") or ""
                if bk:
                    broker_map.setdefault(bk, {
                        "broker_key": bk,
                        "name": row.get("name", ""),
                        "firm": row.get("firm", ""),
                        "deal_volume": row.get("deal_volume") or 0,
                        "community_id": row.get("community_id"),
                        "market_match": 0,
                        "ac_match": 0,
                    })
                    broker_map[bk]["market_match"] = 1

            # Asset-class specialization candidates
            for r in session.run(_FIND_BROKERS_ASSET_CLASS, asset_class=asset_class):
                row = dict(r)
                bk = row.get("broker_key") or ""
                if bk:
                    broker_map.setdefault(bk, {
                        "broker_key": bk,
                        "name": row.get("name", ""),
                        "firm": row.get("firm", ""),
                        "deal_volume": row.get("deal_volume") or 0,
                        "community_id": row.get("community_id"),
                        "market_match": 0,
                        "ac_match": 0,
                    })
                    broker_map[bk]["ac_match"] = 1
                    if not broker_map[bk].get("community_id") and row.get("community_id"):
                        broker_map[bk]["community_id"] = row.get("community_id")

    except Exception as exc:
        log.error("recommend_broker_candidates_failed", error=str(exc))
        return {
            "status": "ERROR",
            "error": str(exc),
            "deal_context": {
                "market": market,
                "asset_class": asset_class,
                "service_line": service_line,
                "client": client_name,
            },
            "brokers": [],
            "truncated": False,
        }

    if not broker_map:
        return {
            "status": "OK",
            "deal_context": {
                "market": market,
                "asset_class": asset_class,
                "service_line": service_line,
                "client": client_name,
            },
            "brokers": [],
            "truncated": False,
            "warnings": [
                f"No brokers found covering market '{market}' or "
                f"specializing in '{asset_class}'. "
                "Check canonical_map.yaml for alternate spellings."
            ],
        }

    # -------------------------------------------------------------------
    # Step 2: Normalise deal volumes across all candidates
    # -------------------------------------------------------------------
    broker_keys_ordered = list(broker_map.keys())
    raw_volumes = [broker_map[bk]["deal_volume"] for bk in broker_keys_ordered]
    norm_volumes = normalise_rank(raw_volumes)
    for i, bk in enumerate(broker_keys_ordered):
        broker_map[bk]["volume_norm"] = norm_volumes[i]

    # -------------------------------------------------------------------
    # Step 3: Get requesting broker's community (for community overlap)
    # -------------------------------------------------------------------
    my_community_id: Optional[int] = None
    if my_broker_key:
        try:
            with driver.session() as session:
                row = session.run(_MY_BROKER_COMMUNITY, broker_key=my_broker_key).single()
                if row:
                    my_community_id = row["community_id"]
        except Exception as exc:
            log.warning("recommend_broker_my_community_failed", error=str(exc))

    # -------------------------------------------------------------------
    # Step 4: SPOC and affinity lookups per candidate broker
    # -------------------------------------------------------------------
    ranked: list[dict] = []

    try:
        with driver.session() as session:
            for bk, bdata in broker_map.items():
                # SPOC lookup
                spoc_entries: list[dict] = []
                spoc_status = "none"
                try:
                    spoc_rows = list(
                        session.run(
                            _FIND_SPOC_FOR_BROKER,
                            broker_key=bk,
                            client_name=client_name,
                        )
                    )
                    for sr in spoc_rows:
                        status = _spoc_status_from_expiry(sr.get("expiration_date"))
                        spoc_entries.append({
                            "client_name": sr["client_name"],
                            "service_line": sr["service_line"],
                            "spoc_status": status,
                        })
                    # Worst case: if ANY active SPOC → active; any expired → expired; else none
                    statuses = [s["spoc_status"] for s in spoc_entries]
                    if "active" in statuses:
                        spoc_status = "active"
                    elif "expired" in statuses:
                        spoc_status = "expired"
                except Exception:
                    pass

                # Predicted affinity score
                affinity_score = 0.0
                try:
                    aff_row = session.run(_FIND_AFFINITY, broker_key=bk).single()
                    if aff_row and aff_row["max_score"] is not None:
                        affinity_score = float(aff_row["max_score"])
                except Exception:
                    pass

                # Community overlap with requesting broker
                community_overlap = bool(
                    my_community_id is not None
                    and bdata.get("community_id") is not None
                    and bdata["community_id"] == my_community_id
                )

                # Weighted ranking
                spoc_val = spoc_value(spoc_status)
                score = weighted_sum({
                    "deal_volume":    (bdata["volume_norm"], BROKER_DEAL_VOLUME_WEIGHT),
                    "specialization": (float(bdata["ac_match"]), BROKER_SPECIALIZATION_WEIGHT),
                    "spoc":           (spoc_val, BROKER_SPOC_WEIGHT),
                    "community":      (float(community_overlap), BROKER_COMMUNITY_WEIGHT),
                    "affinity":       (min(affinity_score, 1.0), BROKER_AFFINITY_WEIGHT),
                })

                # Build reason strings
                reasons: list[str] = []
                if bdata["market_match"]:
                    reasons.append(f"Covers {market} market")
                if bdata["ac_match"]:
                    reasons.append(f"Specializes in {asset_class}")
                if spoc_status == "active":
                    reasons.append(f"Active SPOC for {client_name or 'matched'} client")
                elif spoc_status == "expired":
                    reasons.append(f"Expired SPOC for {client_name or 'matched'} client")
                if community_overlap:
                    reasons.append("In same Louvain community as requesting broker")
                if affinity_score > 0.5:
                    reasons.append(f"Predicted affinity score {affinity_score:.2f}")

                ranked.append({
                    "broker": {
                        "id": bk,
                        "name": bdata["name"],
                        "firm": bdata["firm"],
                    },
                    "score": score,
                    "components": {
                        "deal_volume_score": round(bdata["volume_norm"], 3),
                        "specialization_match": bool(bdata["ac_match"]),
                        "market_coverage_match": bool(bdata["market_match"]),
                        "spoc_status": spoc_status,
                        "community_overlap": community_overlap,
                        "predicted_affinity_score": round(affinity_score, 3),
                    },
                    "reasons": reasons,
                    "existing_spoc_for_clients": [
                        s for s in spoc_entries
                        if s.get("service_line", "").lower() == service_line.lower()
                        or not service_line
                    ],
                    "community_id": bdata.get("community_id"),
                })

    except Exception as exc:
        log.error("recommend_broker_scoring_failed", error=str(exc))
        return {
            "status": "ERROR",
            "error": str(exc),
            "deal_context": {
                "market": market,
                "asset_class": asset_class,
                "service_line": service_line,
                "client": client_name,
            },
            "brokers": [],
            "truncated": False,
        }

    ranked = stable_sort(ranked, key_field="score")[:k]

    return {
        "status": "OK",
        "deal_context": {
            "market": market,
            "asset_class": asset_class,
            "service_line": service_line,
            "client": client_name,
        },
        "brokers": ranked,
        "truncated": len(broker_map) > k,
    }


def register(mcp_server, driver_factory):
    """Register the recommend_broker_for_deal tool."""

    @mcp_server.tool(
        name="recommend_broker_for_deal",
        description=(
            "Recommend the best-fit broker(s) for a deal given its market, asset class, "
            "and service line. Ranks by deal volume in market, specialization match, "
            "active SPOC assignments, and graph community alignment. "
            "Use this when the user asks 'who should work this deal?', "
            "'best broker for X market Y asset class Z service line', or "
            "'Who is the best broker to work with me on this deal based on preferences?'. "
            "Required: market, asset_class, service_line. "
            "Optional: client_name (SPOC matches boosted), my_broker_key (community overlap), "
            "k (default 5). "
            "Expired SPOCs are included and flagged — never silently dropped."
        ),
    )
    async def recommend_broker_for_deal(
        market: str,
        asset_class: str,
        service_line: str,
        client_name: Optional[str] = None,
        my_broker_key: Optional[str] = None,
        k: int = 5,
    ) -> dict:
        driver = driver_factory()
        return await run_recommend_broker_for_deal(
            driver,
            market=market,
            asset_class=asset_class,
            service_line=service_line,
            client_name=client_name,
            my_broker_key=my_broker_key,
            k=k,
        )
