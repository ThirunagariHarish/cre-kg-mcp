"""
Streaming insight ingester.

Long-lived process that polls HACKATHON.PUBLIC.CRE_INSIGHTS_DELTA every
INGEST_POLL_SECONDS (default 60) for unprocessed rows, upserts Insight nodes
into Neo4j with :ABOUT edges, and stamps body embeddings using
sentence-transformers all-MiniLM-L6-v2 (384-dim).

Entrypoint: python -m ingester.streaming
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import snowflake.connector
import structlog
from dotenv import load_dotenv

from ingester.embedding import encode as _embedding_encode
from ingester.graph_writer import get_driver, bootstrap_schema
from ingester.normalizer import canonical_resolver
from ingester.snowflake_client import get_connection

load_dotenv()

log = structlog.get_logger()

INGEST_POLL_SECONDS: int = int(os.environ.get("INGEST_POLL_SECONDS", 60))


# ---------------------------------------------------------------------------
# Embedding helper — delegates to shared ingester.embedding module (N-P2-1)
# ---------------------------------------------------------------------------


def embed_text(text: str) -> list[float]:
    """Return a 384-dim embedding for the given text (CPU-friendly)."""
    return _embedding_encode(text)


# ---------------------------------------------------------------------------
# Snowflake helpers
# ---------------------------------------------------------------------------

FETCH_UNPROCESSED_SQL = """
SELECT
  INSIGHT_ID, TITLE, BODY, SOURCE, AUTHOR,
  PUBLISHED_AT, INGESTED_AT, MARKET, SUBMARKET, ASSET_CLASS,
  TENANT_NAME, PROPERTY_HINT, RAW_TAGS, SENTIMENT, IMPACT
FROM HACKATHON.PUBLIC.CRE_INSIGHTS_DELTA
WHERE PROCESSED = FALSE
ORDER BY DELTA_CREATED_AT
LIMIT 200
"""

MARK_PROCESSED_SQL = """
UPDATE HACKATHON.PUBLIC.CRE_INSIGHTS_DELTA
SET PROCESSED = TRUE
WHERE INSIGHT_ID = %s
  AND PROCESSED = FALSE
"""

# M-P2-2: bulk-insert backfilled IDs into the delta table so the poll loop
# skips them.  The VALUES rows are built at runtime; the SQL template itself
# intentionally has no VALUES clause — it is appended in bulk_mark_backfilled.
_BACKFILL_MARK_PROCESSED_PREFIX = """
INSERT INTO HACKATHON.PUBLIC.CRE_INSIGHTS_DELTA
  (INSIGHT_ID, PROCESSED, DELTA_CREATED_AT)
VALUES
"""


def fetch_unprocessed(conn: snowflake.connector.SnowflakeConnection) -> list[dict[str, Any]]:
    with conn.cursor(snowflake.connector.DictCursor) as cur:
        cur.execute(FETCH_UNPROCESSED_SQL)
        return cur.fetchall()


def mark_processed(conn: snowflake.connector.SnowflakeConnection, insight_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(MARK_PROCESSED_SQL, (insight_id,))


def bulk_mark_backfilled(
    conn: snowflake.connector.SnowflakeConnection,
    insight_ids: list[str],
) -> None:
    """
    M-P2-2: Bulk-insert all backfilled INSIGHT_IDs into CRE_INSIGHTS_DELTA
    with PROCESSED=TRUE so the poll loop's WHERE PROCESSED=FALSE clause skips
    them.  Uses a single multi-VALUES INSERT — not one row per round-trip.
    """
    if not insight_ids:
        return
    # Build (%s, TRUE, CURRENT_TIMESTAMP()) rows for a single INSERT
    placeholders = ", ".join("(%s, TRUE, CURRENT_TIMESTAMP())" for _ in insight_ids)
    sql = _BACKFILL_MARK_PROCESSED_PREFIX + placeholders
    with conn.cursor() as cur:
        cur.execute(sql, insight_ids)


# ---------------------------------------------------------------------------
# Snowflake backfill-from-source (used to seed Neo4j from CRE_MARKET_INSIGHTS
# for all 50 rows that pre-date the stream — stream only captures future inserts)
# ---------------------------------------------------------------------------

FETCH_ALL_SOURCE_SQL = """
SELECT
  INSIGHT_ID, TITLE, BODY, SOURCE, AUTHOR,
  PUBLISHED_AT, INGESTED_AT, MARKET, SUBMARKET, ASSET_CLASS,
  TENANT_NAME, PROPERTY_HINT, RAW_TAGS, SENTIMENT, IMPACT
FROM HACKATHON.PUBLIC.CRE_MARKET_INSIGHTS
ORDER BY PUBLISHED_AT
"""


def fetch_all_source_insights(conn: snowflake.connector.SnowflakeConnection) -> list[dict[str, Any]]:
    with conn.cursor(snowflake.connector.DictCursor) as cur:
        cur.execute(FETCH_ALL_SOURCE_SQL)
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Neo4j Cypher templates
# ---------------------------------------------------------------------------

INSIGHT_MERGE_CYPHER = """
MERGE (i:Insight {insight_id: $insight_id})
SET i.title        = $title,
    i.body         = $body,
    i.source       = $source,
    i.author       = $author,
    i.published_at = $published_at,
    i.ingested_at  = datetime(),
    i.sentiment    = $sentiment,
    i.impact       = $impact,
    i.raw_tags     = $raw_tags,
    i.embedding    = $embedding,
    i.market       = $market,
    i.asset_class  = $asset_class,
    i.last_seen    = datetime()
RETURN i.insight_id AS id
"""

ABOUT_MARKET_CYPHER = """
MATCH (i:Insight {insight_id: $insight_id})
MERGE (m:Market {name: $name})
ON CREATE SET m.display_name = $display_name, m.last_seen = datetime()
ON MATCH  SET m.last_seen    = datetime()
MERGE (i)-[:ABOUT]->(m)
"""

ABOUT_SUBMARKET_CYPHER = """
MATCH (i:Insight {insight_id: $insight_id})
MERGE (s:Submarket {name: $name})
ON CREATE SET s.display_name = $display_name, s.last_seen = datetime()
ON MATCH  SET s.last_seen    = datetime()
MERGE (i)-[:ABOUT]->(s)
"""

ABOUT_ASSET_CLASS_CYPHER = """
MATCH (i:Insight {insight_id: $insight_id})
MERGE (a:AssetClass {name: $name})
ON CREATE SET a.display_name = $display_name, a.last_seen = datetime()
ON MATCH  SET a.last_seen    = datetime()
MERGE (i)-[:ABOUT]->(a)
"""

ABOUT_TENANT_CYPHER = """
MATCH (i:Insight {insight_id: $insight_id})
MERGE (t:Tenant {tenant_key: $tenant_key})
ON CREATE SET t.name = $name, t.last_seen = datetime()
ON MATCH  SET t.last_seen = datetime()
MERGE (i)-[:ABOUT]->(t)
"""

ABOUT_PROPERTY_CYPHER = """
MATCH (i:Insight {insight_id: $insight_id})
MATCH (p:Property {property_key: $property_key})
MERGE (i)-[:ABOUT]->(p)
"""

# Generic tag ABOUT edge — for tags resolved via canonical_resolver
ABOUT_TAG_CYPHER_MAP = {
    "Market": ABOUT_MARKET_CYPHER,
    "Submarket": ABOUT_SUBMARKET_CYPHER,
    "AssetClass": ABOUT_ASSET_CLASS_CYPHER,
}


# ---------------------------------------------------------------------------
# Core upsert logic
# ---------------------------------------------------------------------------

def _parse_raw_tags(raw_tags_val: Any) -> list[str]:
    """Parse raw_tags field from Snowflake (may be JSON string, list, dict, or None)."""
    if raw_tags_val is None:
        return []
    if isinstance(raw_tags_val, list):
        return [str(t) for t in raw_tags_val]
    # N-P2-5: Snowflake VARIANT can return a dict when the stored JSON is an
    # object rather than an array (malformed producer data).  Log and skip
    # rather than coercing with str() which produces unparseable tag keys.
    if isinstance(raw_tags_val, dict):
        log.warning("raw_tags_is_dict_not_list", keys=list(raw_tags_val.keys())[:10])
        return []
    if isinstance(raw_tags_val, str):
        try:
            parsed = json.loads(raw_tags_val)
            if isinstance(parsed, list):
                return [str(t) for t in parsed]
            if isinstance(parsed, dict):
                log.warning("raw_tags_json_is_dict_not_list", keys=list(parsed.keys())[:10])
                return []
        except (json.JSONDecodeError, ValueError):
            pass
        # Comma-separated fallback
        return [t.strip() for t in raw_tags_val.split(",") if t.strip()]
    return []


def upsert_insight(neo4j_driver, row: dict[str, Any], embedding: list[float]) -> None:
    """
    Upsert a single Insight node and all :ABOUT edges into Neo4j.
    Idempotent — safe to call multiple times with the same insight_id.
    """
    insight_id = str(row["INSIGHT_ID"]).strip()
    raw_tags = _parse_raw_tags(row.get("RAW_TAGS"))

    published_at = row.get("PUBLISHED_AT")
    if published_at is not None:
        published_at = str(published_at)

    sentiment = row.get("SENTIMENT")
    if sentiment is not None:
        try:
            sentiment = float(sentiment)
        except (TypeError, ValueError):
            sentiment = None

    with neo4j_driver.session() as session:
        # Canonical market / asset_class for node properties
        from ingester.normalizer import taxonomy_key as _taxonomy_key
        market_val_raw = (row.get("MARKET") or "").strip()
        asset_class_val_raw = (row.get("ASSET_CLASS") or "").strip()
        canonical_market_prop = _taxonomy_key(market_val_raw, "markets") if market_val_raw else None
        canonical_ac_prop = _taxonomy_key(asset_class_val_raw, "asset_classes") if asset_class_val_raw else None

        # 1. Upsert Insight node with embedding
        session.run(
            INSIGHT_MERGE_CYPHER,
            insight_id=insight_id,
            title=(row.get("TITLE") or "").strip(),
            body=(row.get("BODY") or "").strip(),
            source=(row.get("SOURCE") or "").strip(),
            author=(row.get("AUTHOR") or "").strip(),
            published_at=published_at,
            sentiment=sentiment,
            impact=(row.get("IMPACT") or "").strip(),
            raw_tags=raw_tags,
            embedding=embedding,
            market=canonical_market_prop,
            asset_class=canonical_ac_prop,
        )

        # 2. Wire :ABOUT to Market (from dedicated MARKET column)
        if market_val_raw and canonical_market_prop:
            session.run(
                ABOUT_MARKET_CYPHER,
                insight_id=insight_id,
                name=canonical_market_prop,
                display_name=market_val_raw,
            )

        # 3. Wire :ABOUT to Submarket (from dedicated SUBMARKET column)
        submarket_val = (row.get("SUBMARKET") or "").strip()
        if submarket_val:
            session.run(
                ABOUT_SUBMARKET_CYPHER,
                insight_id=insight_id,
                name=submarket_val.lower(),
                display_name=submarket_val,
            )

        # 4. Wire :ABOUT to AssetClass (from dedicated ASSET_CLASS column)
        if asset_class_val_raw and canonical_ac_prop:
            session.run(
                ABOUT_ASSET_CLASS_CYPHER,
                insight_id=insight_id,
                name=canonical_ac_prop,
                display_name=asset_class_val_raw,
            )

        # 5. Wire :ABOUT to Tenant (from TENANT_NAME column)
        tenant_val = (row.get("TENANT_NAME") or "").strip()
        if tenant_val:
            t_key = f"name::{tenant_val.lower()}"
            session.run(
                ABOUT_TENANT_CYPHER,
                insight_id=insight_id,
                tenant_key=t_key,
                name=tenant_val,
            )

        # 6. Wire :ABOUT from free-form RAW_TAGS via canonical_resolver
        unmapped: list[str] = []
        for tag in raw_tags:
            resolved = canonical_resolver(tag)
            if resolved is None:
                unmapped.append(tag)
                continue
            label, name = resolved
            cypher = ABOUT_TAG_CYPHER_MAP.get(label)
            if cypher:
                session.run(
                    cypher,
                    insight_id=insight_id,
                    name=name,
                    display_name=name,
                )
            elif label == "Tenant":
                session.run(
                    ABOUT_TENANT_CYPHER,
                    insight_id=insight_id,
                    tenant_key=name,
                    name=name.replace("name::", ""),
                )
            elif label == "Property":
                session.run(
                    ABOUT_PROPERTY_CYPHER,
                    insight_id=insight_id,
                    property_key=name,
                )

        if unmapped:
            log.warning(
                "unmapped_insight_tags",
                insight_id=insight_id,
                unmapped_count=len(unmapped),
                tags=unmapped,
            )


# ---------------------------------------------------------------------------
# Poll loop
# ---------------------------------------------------------------------------

def run_once(sf_conn, neo4j_driver) -> int:
    """
    Single poll cycle: fetch unprocessed delta rows, upsert, mark processed.
    Returns count of rows processed.
    """
    rows = fetch_unprocessed(sf_conn)
    if not rows:
        log.info("no_new_insights")
        return 0

    log.info("processing_insights", count=len(rows))
    processed_count = 0
    for row in rows:
        insight_id = str(row["INSIGHT_ID"]).strip()
        body = (row.get("BODY") or row.get("TITLE") or insight_id)
        try:
            emb = embed_text(body)
            upsert_insight(neo4j_driver, row, emb)
            mark_processed(sf_conn, insight_id)
            processed_count += 1
            log.info("insight_upserted", insight_id=insight_id)
        except Exception as exc:
            log.error("insight_upsert_failed", insight_id=insight_id, error=str(exc))

    return processed_count


def backfill_from_source(sf_conn, neo4j_driver) -> int:
    """
    One-shot backfill of all rows in CRE_MARKET_INSIGHTS that are NOT yet
    in Neo4j.  This seeds the 50 seeded rows (which predate the Stream).
    Uses Neo4j MERGE so it is idempotent.
    """
    rows = fetch_all_source_insights(sf_conn)
    log.info("backfill_source_rows", total=len(rows))

    # Check which insight_ids already exist in Neo4j
    existing_ids: set[str] = set()
    with neo4j_driver.session() as session:
        result = session.run("MATCH (i:Insight) RETURN i.insight_id AS id")
        existing_ids = {r["id"] for r in result}

    log.info("existing_insight_nodes", count=len(existing_ids))
    new_rows = [r for r in rows if str(r["INSIGHT_ID"]).strip() not in existing_ids]
    log.info("backfill_new_rows", count=len(new_rows))

    count = 0
    backfilled_ids: list[str] = []
    for row in new_rows:
        insight_id = str(row["INSIGHT_ID"]).strip()
        body = (row.get("BODY") or row.get("TITLE") or insight_id)
        try:
            emb = embed_text(body)
            upsert_insight(neo4j_driver, row, emb)
            backfilled_ids.append(insight_id)
            count += 1
            log.info("backfill_insight_upserted", insight_id=insight_id)
        except Exception as exc:
            log.error("backfill_insight_failed", insight_id=insight_id, error=str(exc))

    # M-P2-2: mark all successfully backfilled rows as processed in the delta
    # table using a single multi-VALUES INSERT so the poll loop's
    # WHERE PROCESSED = FALSE clause skips them on future cycles.
    if backfilled_ids:
        try:
            bulk_mark_backfilled(sf_conn, backfilled_ids)
            log.info("backfill_marked_processed", count=len(backfilled_ids))
        except Exception as exc:
            log.warning(
                "backfill_mark_processed_failed",
                error=str(exc),
                count=len(backfilled_ids),
            )

    return count


def run_poll_loop(sf_conn, neo4j_driver, poll_seconds: int = INGEST_POLL_SECONDS) -> None:
    """Infinite poll loop. Ctrl-C / SIGTERM to stop."""
    log.info("poll_loop_starting", poll_seconds=poll_seconds)
    while True:
        try:
            count = run_once(sf_conn, neo4j_driver)
            log.info("poll_cycle_done", processed=count)
        except Exception as exc:
            log.error("poll_cycle_error", error=str(exc))
        time.sleep(poll_seconds)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv()
    sf_conn = get_connection()
    neo4j_driver = get_driver()

    log.info("streaming_ingester_starting")

    # Bootstrap schema (idempotent)
    bootstrap_schema(neo4j_driver)

    # Seed existing 50 insights from source table (stream only captures future rows)
    backfill_from_source(sf_conn, neo4j_driver)

    # Start continuous poll loop
    run_poll_loop(sf_conn, neo4j_driver)


if __name__ == "__main__":
    main()
