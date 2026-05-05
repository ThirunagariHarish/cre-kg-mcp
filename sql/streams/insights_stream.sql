-- =============================================================================
-- CRE Market Insights — Snowflake Stream + Task Setup
-- Idempotent: safe to re-run.
-- M-P2-3: SUSPEND Task before any DDL that touches CRE_INSIGHTS_DELTA, then
--         RESUME at the end.  Delta table uses CREATE TABLE IF NOT EXISTS so
--         re-running never drops live unprocessed rows.
-- =============================================================================
-- Source table: HACKATHON.PUBLIC.CRE_MARKET_INSIGHTS (already exists, 50 rows)
--
-- Objects created:
--   1. CRE_INSIGHTS_STREAM  — append-only stream on the source table
--   2. CRE_INSIGHTS_DELTA   — staging table the Task materialises rows into
--   3. CRE_INSIGHTS_TASK    — task that runs every 1 minute, moves stream
--                              rows to CRE_INSIGHTS_DELTA with processed=FALSE
-- =============================================================================

USE DATABASE HACKATHON;
USE SCHEMA PUBLIC;

-- Step 1: Stream on source table (append-only — we care about new inserts only)
CREATE OR REPLACE STREAM HACKATHON.PUBLIC.CRE_INSIGHTS_STREAM
  ON TABLE HACKATHON.PUBLIC.CRE_MARKET_INSIGHTS
  APPEND_ONLY = TRUE;

-- Step 2a: M-P2-3 — SUSPEND the task before touching the delta table.
--   IF EXISTS prevents a hard error on first run when the task doesn't yet exist.
ALTER TASK IF EXISTS HACKATHON.PUBLIC.CRE_INSIGHTS_TASK SUSPEND;

-- Step 2b: Delta / staging table for the ingester to poll.
--   CREATE TABLE IF NOT EXISTS preserves live unprocessed rows on re-run.
--   (On first run it creates the table; subsequent runs are no-ops here.)
CREATE TABLE IF NOT EXISTS HACKATHON.PUBLIC.CRE_INSIGHTS_DELTA (
  INSIGHT_ID      STRING        NOT NULL,
  TITLE           STRING,
  BODY            STRING,
  SOURCE          STRING,
  AUTHOR          STRING,
  PUBLISHED_AT    TIMESTAMP_NTZ,
  INGESTED_AT     TIMESTAMP_NTZ,
  MARKET          STRING,
  SUBMARKET       STRING,
  ASSET_CLASS     STRING,
  TENANT_NAME     STRING,
  PROPERTY_HINT   STRING,
  RAW_TAGS        VARIANT,
  SENTIMENT       FLOAT,
  IMPACT          STRING,
  PROCESSED       BOOLEAN       NOT NULL DEFAULT FALSE,
  DELTA_CREATED_AT TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

-- Step 3: Task that materialises new stream rows into the delta table.
--   Schedule: 1 MINUTE (minimum allowed; aligns with ingester 60-s poll).
--   Warehouse: parameterised via env var at setup time; falls back to COMPUTE_WH.
--   The task only fires when the stream has new rows (WHEN SYSTEM$STREAM_HAS_DATA).
--   CREATE OR REPLACE TASK is safe here — the task body is idempotent and we
--   SUSPENDed before this block so no in-flight execution is interrupted.
CREATE OR REPLACE TASK HACKATHON.PUBLIC.CRE_INSIGHTS_TASK
  WAREHOUSE = COMPUTE_WH
  SCHEDULE  = '1 MINUTE'
  WHEN SYSTEM$STREAM_HAS_DATA('HACKATHON.PUBLIC.CRE_INSIGHTS_STREAM')
AS
  INSERT INTO HACKATHON.PUBLIC.CRE_INSIGHTS_DELTA
    (INSIGHT_ID, TITLE, BODY, SOURCE, AUTHOR,
     PUBLISHED_AT, INGESTED_AT, MARKET, SUBMARKET, ASSET_CLASS,
     TENANT_NAME, PROPERTY_HINT, RAW_TAGS, SENTIMENT, IMPACT,
     PROCESSED, DELTA_CREATED_AT)
  SELECT
    INSIGHT_ID, TITLE, BODY, SOURCE, AUTHOR,
    PUBLISHED_AT, INGESTED_AT, MARKET, SUBMARKET, ASSET_CLASS,
    TENANT_NAME, PROPERTY_HINT, RAW_TAGS, SENTIMENT, IMPACT,
    FALSE,
    CURRENT_TIMESTAMP()
  FROM HACKATHON.PUBLIC.CRE_INSIGHTS_STREAM;

-- Step 4: Resume the task (tasks are SUSPENDED by default after CREATE OR REPLACE)
ALTER TASK HACKATHON.PUBLIC.CRE_INSIGHTS_TASK RESUME;

-- Verification queries (run manually to confirm):
-- SHOW STREAMS  LIKE 'CRE_INSIGHTS_STREAM' IN SCHEMA HACKATHON.PUBLIC;
-- SHOW TASKS    LIKE 'CRE_INSIGHTS_TASK'   IN SCHEMA HACKATHON.PUBLIC;
-- SELECT COUNT(*) FROM HACKATHON.PUBLIC.CRE_INSIGHTS_DELTA;
