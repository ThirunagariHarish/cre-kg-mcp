"""
Snowflake connector module.

Auth: username + password (not externalbrowser — that blocks stdio processes).
Connection parameters come from environment variables via python-dotenv.
"""

from __future__ import annotations

import os
from typing import Any, Generator

import snowflake.connector
import structlog
from dotenv import load_dotenv

load_dotenv()

log = structlog.get_logger()

TABLES_TO_PROBE = [
    "CRE_BROKERS",
    "CRE_PROPERTIES",
    "CRE_LEASE_COMPS",
    "CRE_PURSUITS",
    "CRE_SPOC",
]


def _get_connection_params() -> dict[str, str]:
    return {
        "account": os.environ["SNOWFLAKE_ACCOUNT"],
        "user": os.environ["SNOWFLAKE_USER"],
        "password": os.environ["SNOWFLAKE_PASSWORD"],
        "role": os.environ.get("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
        "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        "database": os.environ.get("SNOWFLAKE_DATABASE", "HACKATHON"),
        "schema": os.environ.get("SNOWFLAKE_SCHEMA", "PUBLIC"),
    }


def get_connection() -> snowflake.connector.SnowflakeConnection:
    """
    Open and return a Snowflake connection.

    Raises snowflake.connector.errors.DatabaseError on auth failure.
    Logs clearly before propagating.
    """
    params = _get_connection_params()
    log.info(
        "snowflake_connecting",
        account=params["account"],
        user=params["user"],
        database=params["database"],
        schema=params["schema"],
    )
    try:
        conn = snowflake.connector.connect(**params)
        log.info("snowflake_connection_ok")
        return conn
    except snowflake.connector.errors.DatabaseError as exc:
        log.error("snowflake_connection_failed", error=str(exc))
        raise


def probe_tables(conn: snowflake.connector.SnowflakeConnection) -> dict[str, str]:
    """
    Run a lightweight SELECT 1 FROM each of the five source tables.

    Returns a dict mapping table_name -> "ok" | "error: <message>".
    Ensures ACCOUNTADMIN can read each table before backfill starts.
    """
    results: dict[str, str] = {}
    with conn.cursor() as cur:
        for table in TABLES_TO_PROBE:
            fqn = f"HACKATHON.PUBLIC.{table}"
            try:
                cur.execute(f"SELECT 1 FROM {fqn} LIMIT 1")
                cur.fetchone()
                results[table] = "ok"
                log.info("table_probe_ok", table=fqn)
            except Exception as exc:
                msg = f"error: {exc}"
                results[table] = msg
                log.error("table_probe_failed", table=fqn, error=str(exc))
    return results


def fetch_all(
    conn: snowflake.connector.SnowflakeConnection,
    table: str,
    batch_size: int = 5000,
) -> Generator[list[dict[str, Any]], None, None]:
    """
    Yield batches of rows from a Snowflake table as list-of-dicts.

    Uses DictCursor so callers can access columns by name regardless of
    column order.
    """
    fqn = f"HACKATHON.PUBLIC.{table}"
    log.info("snowflake_fetch_start", table=fqn)
    with conn.cursor(snowflake.connector.DictCursor) as cur:
        cur.execute(f"SELECT * FROM {fqn}")
        total = 0
        while True:
            batch = cur.fetchmany(batch_size)
            if not batch:
                break
            total += len(batch)
            log.debug("snowflake_batch_fetched", table=fqn, batch_size=len(batch), total_so_far=total)
            yield batch
    log.info("snowflake_fetch_done", table=fqn, total_rows=total)
