"""
ml/refresh.py — ML enrichment refresh worker.

Runs embeddings → communities → link prediction on a 10-minute cadence.
The override path (M-P3-2 FIX) is exposed as a SEPARATE method `maybe_trigger_now()`
that callers (e.g. ingester after a batch flush) invoke directly — it is NOT part
of the scheduler tick.

Last-run metadata is stored in a Neo4j node:
  (:MLRunMeta {key: "global", last_run_at: datetime, new_insights_since: int})

Entrypoint: python -m ml.refresh  (long-lived process)
           python -m ml.refresh --once  (run pipeline once and exit — M-P3-1)
"""

from __future__ import annotations

import os
import signal
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


def maybe_trigger_now(driver: Driver) -> bool:
    """
    M-P3-2 FIX: Separate override method for external callers.

    Callers (e.g. ingester/streaming.py after a batch flush) invoke this method
    when they suspect the override condition is met (≥50 new insights since last run).
    Returns True if the pipeline was triggered, False otherwise.

    This is NOT called from tick() — tick() always fires the pipeline unconditionally
    on the 10-minute schedule.
    """
    try:
        with driver.session() as session:
            last_run_at = _get_last_run_time(session)
            if _should_override(session, last_run_at):
                log.info("ml_override_pipeline_fire")
                run_ml_pipeline(driver)
                return True
        return False
    except Exception as exc:
        log.warning("maybe_trigger_now_failed", error=str(exc))
        return False


def start_scheduler() -> None:
    """
    Start APScheduler with IntervalTrigger(minutes=10).

    M-P3-2 FIX: tick() always runs the pipeline unconditionally on each scheduled
    interval. The override path (based on insight count) is exposed separately as
    maybe_trigger_now() for callers that want to trigger early.

    N-P3-4: Registers SIGTERM handler so Docker compose down doesn't kill mid-write.
    """
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    driver = _get_driver()

    def tick() -> None:
        """Scheduled tick — always fires the full ML pipeline."""
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

    # N-P3-4: SIGTERM handler — graceful shutdown
    def _sigterm_handler(*_) -> None:
        log.info("ml_refresh_sigterm_received")
        scheduler.shutdown(wait=False)
        driver.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _sigterm_handler)

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
    import argparse

    # M-P3-1: --once flag — run pipeline once and exit
    parser = argparse.ArgumentParser(description="ML enrichment refresh worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run the ML pipeline once and exit (instead of starting the scheduler)",
    )
    args = parser.parse_args()

    if args.once:
        log.info("ml_refresh_once_mode")
        result = run_ml_pipeline()
        print(result)
        sys.exit(0 if result.get("status") == "OK" else 1)
    else:
        start_scheduler()
