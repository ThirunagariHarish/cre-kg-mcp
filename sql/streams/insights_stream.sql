-- =============================================================================
-- CRE Market Insights — Snowflake Stream + Task Setup
-- Idempotent: safe to re-run; uses CREATE OR REPLACE / IF NOT EXISTS
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

-- Step 2: Delta / staging table for the ingester to poll
--   processed BOOLEAN tracks which rows the Python ingester has consumed.
--   Re-running this statement is safe: OR REPLACE recreates the empty schema.
--   (Live rows in an existing DELTA table will be lost; this is acceptable
--   at hackathon scale — the ingester's Neo4j MERGE is idempotent.)
CREATE OR REPLACE TABLE HACKATHON.PUBLIC.CRE_INSIGHTS_DELTA (
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

-- Step 3: Task that materialises new stream rows into the delta table
--   Schedule: 1 MINUTE (minimum allowed; aligns with ingester 60-s poll).
--   Warehouse: parameterised via env var at setup time; falls back to COMPUTE_WH.
--   The task only fires when the stream has new rows (WHEN SYSTEM$STREAM_HAS_DATA).
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

-- Step 4: Resume the task (tasks are SUSPENDED by default after CREATE)
ALTER TASK HACKATHON.PUBLIC.CRE_INSIGHTS_TASK RESUME;

-- Verification queries (run manually to confirm):
-- SHOW STREAMS  LIKE 'CRE_INSIGHTS_STREAM' IN SCHEMA HACKATHON.PUBLIC;
-- SHOW TASKS    LIKE 'CRE_INSIGHTS_TASK'   IN SCHEMA HACKATHON.PUBLIC;
-- SELECT COUNT(*) FROM HACKATHON.PUBLIC.CRE_INSIGHTS_DELTA;
