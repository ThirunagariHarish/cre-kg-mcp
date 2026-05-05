"""
ml/refresh.py — ML enrichment refresh worker.

Runs embeddings → communities → link prediction on a 10-minute cadence.
Override: if ≥50 new Insight nodes have been ingested since last run,
fire immediately and update last_run_time in the :MLRunMeta singleton node.

Last-run metadata is stored in a Neo4j node:
  (:MLRunMeta {key: "global", last_run_at: datetime, new_insights_since: int})

Entrypoint: python -m ml.refresh  (long-lived process)
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

# Imported at module level so tests can patch ml.refresh.run_embeddings etc.
from ml.embeddings import run_embeddings  # noqa: E402
from ml.communities import run_communities  # noqa: E402
from ml.link_prediction import run_link_prediction  # noqa: E402

NEW_INSIGHT_THRESHOLD = 50
ML_META_KEY = "global"


def _get_driver() -> Driver:
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "hackathon_local_only")
    return GraphDatabase.driver(uri, auth=(user, password))


def _get_last_run_time(session) -> datetime | None:
    """Read last_run_at from :MLRunMeta {key:'global'}. Returns None if not set."""
    result = session.run(
        "MATCH (m:MLRunMeta {key: $key}) RETURN m.last_run_at AS last_run_at",
        key=ML_META_KEY,
    )
    row = result.single()
    if row is None or row["last_run_at"] is None:
        return None
    val = row["last_run_at"]
    # Neo4j datetime → Python datetime
    if hasattr(val, "to_native"):
        dt = val.to_native()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return None


def _update_last_run_time(session, run_at: datetime) -> None:
    """Upsert :MLRunMeta {key:'global'} with the current run timestamp."""
    session.run(
        """
        MERGE (m:MLRunMeta {key: $key})
        SET m.last_run_at = datetime($run_at)
        """,
        key=ML_META_KEY,
        run_at=run_at.isoformat(),
    )


def _count_new_insights(session, since: datetime | None) -> int:
    """
    Count Insight nodes ingested after `since`.
    If since is None, count all Insight nodes.
    """
    if since is None:
        result = session.run("MATCH (i:Insight) RETURN count(i) AS cnt")
    else:
        result = session.run(
            """
            MATCH (i:Insight)
            WHERE i.ingested_at > datetime($last_run_time)
            RETURN count(i) AS cnt
            """,
            last_run_time=since.isoformat(),
        )
    row = result.single()
    return row["cnt"] if row else 0


def run_ml_pipeline(driver: Driver | None = None) -> dict[str, Any]:
    """
    Run the full ML pipeline: embeddings → communities → link prediction.
    Updates :MLRunMeta after successful completion.
    """
    close_after = driver is None
    if driver is None:
        driver = _get_driver()

    run_at = datetime.now(timezone.utc)
    log.info("ml_pipeline_starting", run_at=run_at.isoformat())

    results: dict[str, Any] = {}
    error: str | None = None

    try:
        emb_result = run_embeddings(driver)
        results["embeddings"] = emb_result
        if emb_result.get("status") != "OK":
            raise RuntimeError(f"Embeddings failed: {emb_result.get('error')}")

        comm_result = run_communities(driver)
        results["communities"] = comm_result
        if comm_result.get("status") != "OK":
            raise RuntimeError(f"Communities failed: {comm_result.get('error')}")

        link_result = run_link_prediction(driver)
        results["link_prediction"] = link_result
        if link_result.get("status") != "OK":
            raise RuntimeError(f"Link prediction failed: {link_result.get('error')}")

        # Update last_run_at
        with driver.session() as session:
            _update_last_run_time(session, run_at)

        log.info("ml_pipeline_complete", run_at=run_at.isoformat())
        return {"status": "OK", "run_at": run_at.isoformat(), "results": results}

    except Exception as exc:
        error = str(exc)
        log.error("ml_pipeline_failed", error=error)
        return {"status": "ERROR", "error": error, "results": results}
    finally:
        if close_after and driver is not None:
            driver.close()


def _should_override(session, last_run_at: datetime | None) -> bool:
    """Return True if ≥50 new insights have arrived since last run."""
    count = _count_new_insights(session, last_run_at)
    if count >= NEW_INSIGHT_THRESHOLD:
        log.info("ml_override_triggered", new_insights=count, threshold=NEW_INSIGHT_THRESHOLD)
        return True
    return False


def start_scheduler() -> None:
    """
    Start APScheduler with IntervalTrigger(minutes=10).
    Also checks override condition on each tick.
    Long-lived — runs until killed.
    """
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    driver = _get_driver()

    def tick() -> None:
        with driver.session() as session:
            last_run_at = _get_last_run_time(session)
            override = _should_override(session, last_run_at)

        if override:
            log.info("ml_refresh_override_fire")
            run_ml_pipeline(driver)
        else:
            log.info("ml_refresh_scheduled_fire")
            run_ml_pipeline(driver)

    scheduler = BlockingScheduler()
    scheduler.add_job(
        tick,
        trigger=IntervalTrigger(minutes=10),
        id="ml_refresh",
        name="ML enrichment refresh",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    log.info("ml_refresh_scheduler_starting", interval_minutes=10)

    # Run once immediately on start so embeddings exist before first scheduled tick
    try:
        log.info("ml_refresh_initial_run")
        run_ml_pipeline(driver)
    except Exception as exc:
        log.warning("ml_refresh_initial_run_failed", error=str(exc))

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("ml_refresh_scheduler_stopped")
        driver.close()


if __name__ == "__main__":
    start_scheduler()
