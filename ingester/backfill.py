"""
Backfill orchestrator.

Locked order per data-model.md §4.2:
  1. CRE_BROKERS
  2. CRE_PROPERTIES
  3. CRE_LEASE_COMPS
  4. CRE_PURSUITS
  5. CRE_SPOC

Run: python -m ingester.backfill  OR  make backfill
"""

from __future__ import annotations

import sys

import structlog
from dotenv import load_dotenv

load_dotenv()

from ingester.snowflake_client import get_connection, probe_tables, fetch_all
from ingester.graph_writer import (
    get_driver,
    bootstrap_schema,
    upsert_broker,
    upsert_property,
    upsert_lease,
    upsert_pursuit,
    upsert_spoc,
)
from ingester.normalizer import (
    broker_key,
    property_key,
    tenant_key,
    landlord_key,
    lease_key,
    client_key,
    broker_key_from_pursuit,
    broker_key_from_spoc,
    taxonomy_key,
)

log = structlog.get_logger()


def run_backfill() -> None:
    log.info("backfill_start")

    # ---- Snowflake ----
    try:
        sf_conn = get_connection()
    except Exception as exc:
        log.error("snowflake_connect_fatal", error=str(exc))
        sys.exit(1)

    probes = probe_tables(sf_conn)
    failed_tables = [t for t, status in probes.items() if status != "ok"]
    if failed_tables:
        log.warning("table_probe_warnings", failed_tables=failed_tables)
        # Continue — partial backfill is better than none

    # ---- Neo4j ----
    driver = get_driver()
    bootstrap_schema(driver)

    counts: dict[str, int] = {}

    # ------------------------------------------------------------------
    # 1. CRE_BROKERS
    # ------------------------------------------------------------------
    log.info("backfill_table", table="CRE_BROKERS")
    n = 0
    with driver.session() as session:
        for batch in fetch_all(sf_conn, "CRE_BROKERS"):
            for row in batch:
                try:
                    bk = broker_key(row)
                    upsert_broker(session, row, bk, taxonomy_key)
                    n += 1
                except Exception as exc:
                    log.warning("broker_row_error", error=str(exc), row_sample=str(row)[:200])
    counts["CRE_BROKERS"] = n
    log.info("backfill_table_done", table="CRE_BROKERS", upserted=n)

    # ------------------------------------------------------------------
    # 2. CRE_PROPERTIES
    # ------------------------------------------------------------------
    log.info("backfill_table", table="CRE_PROPERTIES")
    n = 0
    with driver.session() as session:
        for batch in fetch_all(sf_conn, "CRE_PROPERTIES"):
            for row in batch:
                try:
                    pk = property_key(row)
                    upsert_property(session, row, pk, landlord_key, taxonomy_key)
                    n += 1
                except Exception as exc:
                    log.warning("property_row_error", error=str(exc), row_sample=str(row)[:200])
    counts["CRE_PROPERTIES"] = n
    log.info("backfill_table_done", table="CRE_PROPERTIES", upserted=n)

    # ------------------------------------------------------------------
    # 3. CRE_LEASE_COMPS
    # ------------------------------------------------------------------
    log.info("backfill_table", table="CRE_LEASE_COMPS")
    n = 0
    with driver.session() as session:
        for batch in fetch_all(sf_conn, "CRE_LEASE_COMPS"):
            for row in batch:
                try:
                    pk = property_key(row)
                    tk = tenant_key(row)
                    lk = landlord_key(row)
                    lsk = lease_key(row)
                    upsert_lease(session, row, lsk, pk, tk, lk, broker_key, taxonomy_key)
                    n += 1
                except Exception as exc:
                    log.warning("lease_row_error", error=str(exc), row_sample=str(row)[:200])
    counts["CRE_LEASE_COMPS"] = n
    log.info("backfill_table_done", table="CRE_LEASE_COMPS", upserted=n)

    # ------------------------------------------------------------------
    # 4. CRE_PURSUITS
    # ------------------------------------------------------------------
    log.info("backfill_table", table="CRE_PURSUITS")
    n = 0
    with driver.session() as session:
        for batch in fetch_all(sf_conn, "CRE_PURSUITS"):
            for row in batch:
                try:
                    ck = client_key(row)
                    upsert_pursuit(session, row, ck, broker_key_from_pursuit, taxonomy_key)
                    n += 1
                except Exception as exc:
                    log.warning("pursuit_row_error", error=str(exc), row_sample=str(row)[:200])
    counts["CRE_PURSUITS"] = n
    log.info("backfill_table_done", table="CRE_PURSUITS", upserted=n)

    # ------------------------------------------------------------------
    # 5. CRE_SPOC
    # ------------------------------------------------------------------
    log.info("backfill_table", table="CRE_SPOC")
    n = 0
    with driver.session() as session:
        for batch in fetch_all(sf_conn, "CRE_SPOC"):
            for row in batch:
                try:
                    bk = broker_key_from_spoc(row)
                    ck = client_key(row)
                    upsert_spoc(session, row, bk, ck, taxonomy_key)
                    n += 1
                except Exception as exc:
                    log.warning("spoc_row_error", error=str(exc), row_sample=str(row)[:200])
    counts["CRE_SPOC"] = n
    log.info("backfill_table_done", table="CRE_SPOC", upserted=n)

    # ------------------------------------------------------------------
    # Node count summary
    # ------------------------------------------------------------------
    with driver.session() as session:
        result = session.run("""
            MATCH (n)
            RETURN labels(n)[0] AS label, count(n) AS cnt
            ORDER BY cnt DESC
        """)
        node_counts = {r["label"]: r["cnt"] for r in result}

    log.info("backfill_complete", source_counts=counts, neo4j_node_counts=node_counts)

    sf_conn.close()
    driver.close()


def main() -> None:
    run_backfill()


if __name__ == "__main__":
    main()
