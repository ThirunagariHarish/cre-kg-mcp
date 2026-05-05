"""
ml/link_prediction.py — Link prediction via Neo4j GDS topological scorers.

B-P3-4 FIX: uses gds.linkprediction.adamicAdar.stream (GDS 2.x procedure namespace)
against the projected graph, NOT the deprecated alpha inline functions.
Falls back to in-Python Adamic-Adar from common-neighbor counts if the procedure
is unavailable.

B-P3-2 FIX: reads from 'embedding' property (not 'node2vec_embedding').

M-P3-3 FIX: prunes stale PredictedLink nodes before persisting new ones.

Scores Broker↔Property and Broker↔Tenant candidate edges.
Persists top-K predictions as :PredictedLink nodes with properties:
  {from_id, from_label, to_id, to_label, score, algo, computed_at}

Helper predict_for_node(node_id, k=10) returns ranked candidates.

Entrypoint: python -m ml.link_prediction
Also importable by ml/refresh.py.
"""

from __future__ import annotations

import math
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

import structlog
from dotenv import load_dotenv
from neo4j import GraphDatabase, Driver

load_dotenv()
log = structlog.get_logger()

PREDICTED_LINK_LABEL = "PredictedLink"
DEFAULT_TOP_K = 50  # persisted per pair type
ALGO_NAME = "adamicAdar"

# GDS graph projection for link prediction
_LP_GRAPH_NAME = "cre-linkpred-projection"
_LP_NODE_LABELS = ["Broker", "Property", "Tenant"]
_LP_REL_TYPES = [
    "COVERS", "SPECIALIZES_IN", "REPRESENTS", "BROKERED_BY",
    "ON", "TENANT_IS", "LOCATED_IN", "CLASSIFIED_AS",
]


def _get_driver() -> Driver:
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "hackathon_local_only")
    return GraphDatabase.driver(uri, auth=(user, password))


def _check_gds_procedure_available(session) -> str:
    """
    B-P3-4: Query CALL gds.list() to find which link prediction procedures exist.
    Returns 'adamicAdar', 'commonNeighbors', or 'fallback' (Python BFS).
    """
    try:
        result = session.run(
            "CALL gds.list() YIELD name WHERE name CONTAINS 'linkprediction' RETURN name"
        )
        names = [row["name"] for row in result]
        log.info("gds_linkprediction_procedures_available", procedures=names)

        for n in names:
            if "adamicAdar" in n and ".stream" in n:
                return "adamicAdar"
        for n in names:
            if "commonNeighbors" in n and ".stream" in n:
                return "commonNeighbors"
        # Procedures exist but stream variants not found — use fallback
        return "fallback"
    except Exception as exc:
        log.warning("gds_list_failed", error=str(exc))
        return "fallback"


def _project_for_link_prediction(gds) -> Any:
    """Create a GDS in-memory projection for link prediction stream procedures."""
    # Drop if exists
    try:
        gds.graph.drop(_LP_GRAPH_NAME)
    except Exception:
        pass

    node_proj = {label: {"label": label} for label in _LP_NODE_LABELS}
    # Use '*' wildcard to project all existing relationship types.
    # Avoids hard failure when some types (e.g. BROKERED_BY) don't exist yet.
    G, stats = gds.graph.project(_LP_GRAPH_NAME, node_proj, "*")
    log.info(
        "lp_projection_created",
        graph_name=_LP_GRAPH_NAME,
        node_count=stats["nodeCount"],
        rel_count=stats["relationshipCount"],
    )
    return G


def _score_pairs_via_procedure(
    session,
    gds,
    from_label: str,
    to_label: str,
    algo: str,
) -> list[dict[str, Any]]:
    """
    B-P3-4: Use gds.linkprediction.<algo>.stream against the projected graph.
    The procedure returns (node1, node2, similarity) for all pairs.
    We filter to only cross-label pairs (from_label → to_label) where no edge exists.
    """
    proc_name = f"gds.linkprediction.{algo}.stream"
    try:
        # Stream over the projected graph; filter by label post-hoc
        cypher = f"""
        CALL {proc_name}(
            $graph_name,
            {{
                sourceNodeFilter: '{from_label}',
                targetNodeFilter: '{to_label}'
            }}
        )
        YIELD node1, node2, similarity
        WHERE NOT (node1)--(node2)
          AND similarity > 0
        WITH node1, node2, similarity
        ORDER BY similarity DESC
        LIMIT $top_k
        RETURN
          coalesce(node1.broker_key, node1.property_key, node1.tenant_key,
                   node1.name, toString(id(node1))) AS from_id,
          coalesce(node2.broker_key, node2.property_key, node2.tenant_key,
                   node2.name, toString(id(node2))) AS to_id,
          similarity AS score
        """
        result = session.run(cypher, graph_name=_LP_GRAPH_NAME, top_k=DEFAULT_TOP_K)
        rows = [
            {
                "from_id": row["from_id"],
                "from_label": from_label,
                "to_id": row["to_id"],
                "to_label": to_label,
                "score": float(row["score"]),
            }
            for row in result
        ]
        log.info("lp_procedure_scored", algo=algo, from_label=from_label,
                 to_label=to_label, count=len(rows))
        return rows
    except Exception as exc:
        log.warning("lp_procedure_failed", algo=algo, error=str(exc))
        return []


def _score_pairs_python_fallback(
    session,
    from_label: str,
    to_label: str,
) -> list[dict[str, Any]]:
    """
    Python Adamic-Adar fallback: compute from common-neighbor counts via Cypher.
    AA(u,v) = sum over w in N(u)∩N(v) of 1/log(degree(w))
    We approximate by querying common neighbor degrees directly.
    Uses the 'embedding' property (B-P3-2) to restrict to embedded nodes only.
    """
    cypher = f"""
    MATCH (a:{from_label}), (b:{to_label})
    WHERE NOT (a)--(b)
      AND a <> b
      AND a.embedding IS NOT NULL
      AND b.embedding IS NOT NULL
    MATCH (a)--(common)--(b)
    WITH a, b, collect(DISTINCT common) AS commons
    WHERE size(commons) > 0
    WITH a, b, commons,
         [w IN commons |
           size([(w)-[]-() | 1])
         ] AS degrees
    WITH a, b,
         reduce(aa = 0.0, i IN range(0, size(degrees)-1) |
           aa + (CASE WHEN degrees[i] > 1 THEN 1.0 / log(toFloat(degrees[i])) ELSE 0.0 END)
         ) AS score
    WHERE score > 0
    RETURN
      coalesce(a.broker_key, a.property_key, a.tenant_key, a.name, toString(id(a))) AS from_id,
      coalesce(b.broker_key, b.property_key, b.tenant_key, b.name, toString(id(b))) AS to_id,
      score
    ORDER BY score DESC
    LIMIT $top_k
    """
    try:
        result = session.run(cypher, top_k=DEFAULT_TOP_K)
        rows = [
            {
                "from_id": row["from_id"],
                "from_label": from_label,
                "to_id": row["to_id"],
                "to_label": to_label,
                "score": float(row["score"]),
            }
            for row in result
        ]
        log.info("lp_python_fallback_scored", from_label=from_label,
                 to_label=to_label, count=len(rows))
        return rows
    except Exception as exc:
        log.warning("lp_python_fallback_failed", error=str(exc))
        return []


def _prune_stale_predictions(session, current_run_at: str) -> int:
    """
    M-P3-3: Delete PredictedLink nodes from previous runs.
    Only deletes nodes whose computed_at < current_run_at (i.e., not from this run).
    Returns count of nodes deleted.
    Uses two queries (count then delete) for Neo4j 5.x compatibility.
    """
    count_result = session.run(
        f"MATCH (pl:{PREDICTED_LINK_LABEL}) WHERE pl.computed_at < $current_run_at "
        f"RETURN count(pl) AS stale_count",
        current_run_at=current_run_at,
    )
    row = count_result.single()
    count = row["stale_count"] if row else 0

    if count > 0:
        session.run(
            f"MATCH (pl:{PREDICTED_LINK_LABEL}) WHERE pl.computed_at < $current_run_at "
            f"DETACH DELETE pl",
            current_run_at=current_run_at,
        )
        log.info("lp_stale_predictions_pruned", deleted=count, before_ts=current_run_at)
    return count


def _persist_predictions(
    session,
    predictions: list[dict[str, Any]],
    algo: str,
    computed_at: str,
) -> int:
    """
    Upsert predictions as :PredictedLink nodes.
    A prediction is identified by (from_id, from_label, to_id, to_label).
    Returns count persisted.
    """
    if not predictions:
        return 0

    cypher = f"""
    UNWIND $rows AS row
    MERGE (pl:{PREDICTED_LINK_LABEL} {{
        from_id: row.from_id,
        from_label: row.from_label,
        to_id: row.to_id,
        to_label: row.to_label
    }})
    SET pl.score = row.score,
        pl.algo = $algo,
        pl.computed_at = $computed_at
    """
    session.run(cypher, rows=predictions, algo=algo, computed_at=computed_at)
    return len(predictions)


def run_link_prediction(driver: Driver | None = None) -> dict[str, Any]:
    """
    Score Broker↔Property and Broker↔Tenant pairs, persist top-K as
    :PredictedLink nodes.  Returns summary dict.

    B-P3-4: Uses gds.linkprediction.<algo>.stream procedures (GDS 2.x namespace).
    Falls back to Python Adamic-Adar if procedures unavailable.
    M-P3-3: Prunes stale PredictedLink nodes before persisting new ones.
    """
    close_after = driver is None
    if driver is None:
        driver = _get_driver()

    try:
        t0 = time.time()
        computed_at = datetime.now(timezone.utc).isoformat()

        with driver.session() as session:
            # Detect available algorithm
            algo = _check_gds_procedure_available(session)
            log.info("link_prediction_starting", algo=algo)

            # M-P3-3: Prune stale predictions first
            pruned = _prune_stale_predictions(session, computed_at)

            broker_property: list[dict[str, Any]] = []
            broker_tenant: list[dict[str, Any]] = []

            if algo in ("adamicAdar", "commonNeighbors"):
                # Use GDS stream procedure via a temporary projection
                try:
                    from graphdatascience import GraphDataScience  # type: ignore
                    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
                    user = os.environ.get("NEO4J_USER", "neo4j")
                    password = os.environ.get("NEO4J_PASSWORD", "hackathon_local_only")
                    gds = GraphDataScience(uri, auth=(user, password))
                    G = _project_for_link_prediction(gds)

                    broker_property = _score_pairs_via_procedure(
                        session, gds, "Broker", "Property", algo
                    )
                    broker_tenant = _score_pairs_via_procedure(
                        session, gds, "Broker", "Tenant", algo
                    )

                    try:
                        gds.graph.drop(_LP_GRAPH_NAME)
                    except Exception:
                        pass
                    gds.close()
                except Exception as exc:
                    log.warning("lp_gds_procedure_path_failed", error=str(exc),
                                fallback="python_adamic_adar")
                    broker_property = _score_pairs_python_fallback(session, "Broker", "Property")
                    broker_tenant = _score_pairs_python_fallback(session, "Broker", "Tenant")
                    algo = "fallback_python_aa"
            else:
                # Direct Python fallback
                broker_property = _score_pairs_python_fallback(session, "Broker", "Property")
                broker_tenant = _score_pairs_python_fallback(session, "Broker", "Tenant")

            all_predictions = broker_property + broker_tenant

            # Persist
            count = _persist_predictions(session, all_predictions, algo, computed_at)

        elapsed = time.time() - t0
        log.info(
            "link_prediction_complete",
            count=count,
            pruned=pruned,
            algo=algo,
            elapsed_s=round(elapsed, 1),
        )

        return {
            "status": "OK",
            "algo": algo,
            "count": count,
            "pruned_stale": pruned,
            "broker_property_count": len(broker_property),
            "broker_tenant_count": len(broker_tenant),
            "elapsed_s": round(elapsed, 1),
            "computed_at": computed_at,
        }

    except Exception as exc:
        log.error("link_prediction_failed", error=str(exc))
        return {"status": "ERROR", "error": str(exc)}
    finally:
        if close_after and driver is not None:
            driver.close()


def predict_for_node(node_id: str, k: int = 10, driver: Driver | None = None) -> list[dict[str, Any]]:
    """
    Return top-k predicted links for a given node_id (from_id or to_id).
    Reads from existing :PredictedLink nodes.

    Returns list of {from_id, from_label, to_id, to_label, score, algo}.
    """
    close_after = driver is None
    if driver is None:
        driver = _get_driver()

    try:
        with driver.session() as session:
            result = session.run(
                f"""
                MATCH (pl:{PREDICTED_LINK_LABEL})
                WHERE pl.from_id = $node_id OR pl.to_id = $node_id
                RETURN pl.from_id AS from_id, pl.from_label AS from_label,
                       pl.to_id AS to_id, pl.to_label AS to_label,
                       pl.score AS score, pl.algo AS algo
                ORDER BY pl.score DESC
                LIMIT $k
                """,
                node_id=node_id,
                k=k,
            )
            return [
                {
                    "from_id": row["from_id"],
                    "from_label": row["from_label"],
                    "to_id": row["to_id"],
                    "to_label": row["to_label"],
                    "score": row["score"],
                    "algo": row["algo"],
                }
                for row in result
            ]
    except Exception as exc:
        log.error("predict_for_node_failed", node_id=node_id, error=str(exc))
        return []
    finally:
        if close_after and driver is not None:
            driver.close()


if __name__ == "__main__":
    result = run_link_prediction()
    print(result)
    if result.get("status") != "OK":
        sys.exit(1)
