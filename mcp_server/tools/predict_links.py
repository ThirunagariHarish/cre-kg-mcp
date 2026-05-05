"""
MCP tool: predict_links

Returns top-k predicted edges (Broker→Property, Broker→Tenant) ranked by score.
Reads from :PredictedLink nodes written by ml/link_prediction.py.

M-P3-5 FIX: JOINs back to source nodes to resolve display names.
  - Broker: returns .name property
  - Property: returns .address_line1 (or property_key if no address)
  - Tenant: returns .name property

Conforms to api-contracts.md §9.
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

log = structlog.get_logger()

# M-P3-5: JOINs back to Broker/Property/Tenant nodes to resolve display names.
# node_id format (from data-model.md §4.1 normalizer key conventions):
#   Brokers: "email::<broker_email>" or "name::<broker_name>::firm::<firm_name>"
#   Properties: "id::<property_id>" or "addr::<address>::zip::<zip>"
#   Tenants: "name::<tenant_name>"
_PREDICTIONS_QUERY = """
MATCH (pl:PredictedLink)
WHERE pl.to_label = $to_label
  AND ($from_node_id IS NULL OR pl.from_id = $from_node_id)
  AND pl.score >= $min_score

// M-P3-5: Resolve from-node display name (always Broker)
OPTIONAL MATCH (from_broker:Broker {broker_key: pl.from_id})

// M-P3-5: Resolve to-node display name (Property or Tenant)
OPTIONAL MATCH (to_prop:Property {property_key: pl.to_id})
OPTIONAL MATCH (to_tenant:Tenant {tenant_key: pl.to_id})

RETURN pl.from_id AS from_id, pl.from_label AS from_label,
       pl.to_id AS to_id, pl.to_label AS to_label,
       pl.score AS score, pl.algo AS algo, pl.computed_at AS computed_at,
       from_broker.name AS broker_name,
       coalesce(to_prop.address_line1, to_prop.property_key) AS property_name,
       to_tenant.name AS tenant_name
ORDER BY pl.score DESC
LIMIT $k
"""

_COUNT_QUERY = "MATCH (pl:PredictedLink) RETURN count(pl) AS cnt"


def _resolve_display_name(row, label: str, node_id: str) -> str:
    """
    M-P3-5: Resolve the human-readable display name for a node.
    Falls back to node_id (merge key) if no display name is available.
    """
    if label == "Broker":
        return row["broker_name"] or node_id
    elif label == "Property":
        return row["property_name"] or node_id
    elif label == "Tenant":
        return row["tenant_name"] or node_id
    return node_id


async def run_predict_links(
    driver,
    *,
    to_label: str,
    from_node_id: Optional[str] = None,
    min_score: float = 0.5,
    k: int = 10,
) -> dict[str, Any]:
    """Core logic — exported for direct test use."""
    if to_label not in ("Property", "Tenant"):
        return {
            "status": "ERROR",
            "error": "to_label must be 'Property' or 'Tenant'",
            "predictions": [],
            "truncated": False,
        }

    try:
        with driver.session() as session:
            # Check if any PredictedLink nodes exist
            cnt_row = session.run(_COUNT_QUERY).single()
            total_count = cnt_row["cnt"] if cnt_row else 0

            if total_count == 0:
                return {
                    "status": "DEGRADED",
                    "error": "Link prediction has not yet run",
                    "predictions": [],
                    "model_version": None,
                    "truncated": False,
                }

            result = session.run(
                _PREDICTIONS_QUERY,
                to_label=to_label,
                from_node_id=from_node_id,
                min_score=min_score,
                k=k,
            )
            rows = list(result)

        if not rows:
            return {
                "status": "OK",
                "predictions": [],
                "model_version": None,
                "caveat": "Link-prediction accuracy is best-effort at hackathon data volumes",
                "truncated": False,
            }

        # Derive model version from computed_at of first row
        first_computed_at = rows[0]["computed_at"] if rows else None
        model_version = f"node2vec-128d-{str(first_computed_at)[:10]}" if first_computed_at else "unknown"

        predictions = []
        for row in rows:
            from_id = row["from_id"]
            from_label = row["from_label"]
            to_id = row["to_id"]
            to_label_val = row["to_label"]

            # M-P3-5: resolve display names from joined source nodes
            from_name = _resolve_display_name(row, from_label, from_id)
            to_name = _resolve_display_name(row, to_label_val, to_id)

            predictions.append(
                {
                    "from": {
                        "id": from_id,
                        "label": from_label,
                        "name": from_name,
                    },
                    "to": {
                        "id": to_id,
                        "label": to_label_val,
                        "name": to_name,
                    },
                    "score": round(float(row["score"]), 4),
                }
            )

        return {
            "status": "OK",
            "model_version": model_version,
            "predictions": predictions,
            "caveat": "Link-prediction accuracy is best-effort at hackathon data volumes",
            "truncated": len(predictions) >= k,
        }

    except Exception as exc:
        log.error("predict_links_failed", error=str(exc))
        return {
            "status": "ERROR",
            "error": str(exc),
            "predictions": [],
            "truncated": False,
        }


def register(mcp_server, driver_factory):
    """Register the predict_links tool on the MCP server instance."""

    @mcp_server.tool(
        name="predict_links",
        description=(
            "Return top-k predicted edges (Broker→Property or Broker→Tenant) ranked by "
            "link-prediction score. Surfaces latent affinities not visible from explicit deal "
            "history. Use this when the user asks 'which properties might this broker be a "
            "good fit for?' or 'find predicted broker-tenant affinities'. "
            "Required: to_label ('Property' or 'Tenant'). "
            "Optional: from_node_id (broker merge key to filter — use 'email::<broker_email>' "
            "for brokers with known email, 'name::<broker_name>::firm::<firm_name>' otherwise; "
            "for properties use 'id::<property_id>' or 'addr::<address>::zip::<zip>'; "
            "for tenants use 'name::<tenant_name>' — see Phase 1 normalizer key conventions). "
            "Optional: min_score (default 0.5), k (default 10). "
            "HACKATHON CAVEAT: scores are best-effort at this data scale."
        ),
    )
    async def predict_links(
        to_label: str,
        from_node_id: Optional[str] = None,
        min_score: float = 0.5,
        k: int = 10,
    ) -> dict:
        driver = driver_factory()
        return await run_predict_links(
            driver,
            to_label=to_label,
            from_node_id=from_node_id,
            min_score=min_score,
            k=k,
        )
