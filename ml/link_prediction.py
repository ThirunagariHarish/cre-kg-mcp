"""
ml/link_prediction.py — Link prediction via Neo4j GDS topological scorers.

Uses gds.alpha.linkprediction.adamicAdar (GDS Community 2.6.9).
Falls back to commonNeighbors if adamicAdar is unavailable.

Scores Broker↔Property and Broker↔Tenant candidate edges.
Persists top-K predictions as :PredictedLink nodes with properties:
  {from_id, from_label, to_id, to_label, score, algo, computed_at}

Helper predict_for_node(node_id, k=10) returns ranked candidates.

Entrypoint: python -m ml.link_prediction
Also importable by ml/refresh.py.
"""

from __future__ import annotations

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


def _get_driver() -> Driver:
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "hackathon_local_only")
    return GraphDatabase.driver(uri, auth=(user, password))


def _score_pairs(
    session,
    from_label: str,
    to_label: str,
    algo: str,
) -> list[dict[str, Any]]:
    """
    Score candidate (from_label, to_label) pairs using the chosen topological
    algorithm.  Returns a list of {from_id, to_id, score} dicts.

    We query candidate pairs that are NOT already directly connected, then
    score each pair using the GDS link-prediction function called inline.
    """
    # Map algorithm name to Cypher function
    algo_fn = {
        "adamicAdar": "gds.alpha.linkprediction.adamicAdar",
        "commonNeighbors": "gds.alpha.linkprediction.commonNeighbors",
    }.get(algo, "gds.alpha.linkprediction.commonNeighbors")

    cypher = f"""
    MATCH (a:{from_label}), (b:{to_label})
    WHERE NOT (a)--(b)
      AND a <> b
      AND a.node2vec_embedding IS NOT NULL
      AND b.node2vec_embedding IS NOT NULL
    WITH a, b,
         {algo_fn}(a, b) AS score
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
        return [
            {
                "from_id": row["from_id"],
                "from_label": from_label,
                "to_id": row["to_id"],
                "to_label": to_label,
                "score": float(row["score"]),
            }
            for row in result
        ]
    except Exception as exc:
        log.warning("link_prediction_score_failed", algo=algo, error=str(exc))
        return []


def _detect_available_algo(session) -> str:
    """
    Try adamicAdar first; fall back to commonNeighbors if it errors.
    Uses a single dummy pair call to probe availability.
    """
    probe = """
    MATCH (a:Broker), (b:Property)
    WHERE a.node2vec_embedding IS NOT NULL AND b.node2vec_embedding IS NOT NULL
    WITH a, b LIMIT 1
    RETURN gds.alpha.linkprediction.adamicAdar(a, b) AS score
    """
    try:
        result = session.run(probe)
        result.single()  # consume
        return "adamicAdar"
    except Exception:
        log.info("link_prediction_algo_fallback", algo="commonNeighbors")
        return "commonNeighbors"


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
    """
    close_after = driver is None
    if driver is None:
        driver = _get_driver()

    try:
        t0 = time.time()
        computed_at = datetime.now(timezone.utc).isoformat()

        with driver.session() as session:
            algo = _detect_available_algo(session)
            log.info("link_prediction_starting", algo=algo)

            # Score both pair types
            broker_property = _score_pairs(session, "Broker", "Property", algo)
            broker_tenant = _score_pairs(session, "Broker", "Tenant", algo)

            all_predictions = broker_property + broker_tenant

            # Persist
            count = _persist_predictions(session, all_predictions, algo, computed_at)

        elapsed = time.time() - t0
        log.info(
            "link_prediction_complete",
            count=count,
            algo=algo,
            elapsed_s=round(elapsed, 1),
        )

        return {
            "status": "OK",
            "algo": algo,
            "count": count,
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
