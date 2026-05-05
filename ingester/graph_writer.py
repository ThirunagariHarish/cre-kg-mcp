"""
Neo4j graph writer: constraint/index bootstrap + idempotent MERGE upserts.

All Cypher is executed via parameterized queries. MERGE is idempotent across
multiple backfill runs — re-running backfill never creates duplicate nodes.

Module boundary note: Phase 2 will add insight/ABOUT upserts here; Phase 3
will add ML property writes. Keep entity-type methods cleanly separated.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from dotenv import load_dotenv
from neo4j import GraphDatabase, Driver, Session

load_dotenv()

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constraint and index DDL (data-model.md §3)
# ---------------------------------------------------------------------------

CONSTRAINTS = [
    "CREATE CONSTRAINT broker_key_unique IF NOT EXISTS FOR (b:Broker) REQUIRE b.broker_key IS UNIQUE",
    "CREATE CONSTRAINT property_key_unique IF NOT EXISTS FOR (p:Property) REQUIRE p.property_key IS UNIQUE",
    "CREATE CONSTRAINT tenant_key_unique IF NOT EXISTS FOR (t:Tenant) REQUIRE t.tenant_key IS UNIQUE",
    "CREATE CONSTRAINT landlord_key_unique IF NOT EXISTS FOR (l:Landlord) REQUIRE l.landlord_key IS UNIQUE",
    "CREATE CONSTRAINT lease_key_unique IF NOT EXISTS FOR (l:Lease) REQUIRE l.lease_key IS UNIQUE",
    "CREATE CONSTRAINT pursuit_id_unique IF NOT EXISTS FOR (p:Pursuit) REQUIRE p.pursuit_id IS UNIQUE",
    "CREATE CONSTRAINT client_key_unique IF NOT EXISTS FOR (c:Client) REQUIRE c.client_key IS UNIQUE",
    "CREATE CONSTRAINT market_name_unique IF NOT EXISTS FOR (m:Market) REQUIRE m.name IS UNIQUE",
    "CREATE CONSTRAINT submarket_name_unique IF NOT EXISTS FOR (s:Submarket) REQUIRE s.name IS UNIQUE",
    "CREATE CONSTRAINT asset_class_name_unique IF NOT EXISTS FOR (a:AssetClass) REQUIRE a.name IS UNIQUE",
    "CREATE CONSTRAINT service_line_name_unique IF NOT EXISTS FOR (s:ServiceLine) REQUIRE s.name IS UNIQUE",
    "CREATE CONSTRAINT firm_name_unique IF NOT EXISTS FOR (f:Firm) REQUIRE f.name IS UNIQUE",
    "CREATE CONSTRAINT insight_id_unique IF NOT EXISTS FOR (i:Insight) REQUIRE i.insight_id IS UNIQUE",
    "CREATE CONSTRAINT community_id_unique IF NOT EXISTS FOR (c:Community) REQUIRE c.community_id IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX broker_name_idx IF NOT EXISTS FOR (b:Broker) ON (b.name)",
    "CREATE INDEX property_city_state_idx IF NOT EXISTS FOR (p:Property) ON (p.city, p.state)",
    "CREATE INDEX pursuit_stage_idx IF NOT EXISTS FOR (p:Pursuit) ON (p.stage)",
    "CREATE INDEX lease_execution_idx IF NOT EXISTS FOR (l:Lease) ON (l.execution_date)",
    "CREATE INDEX broker_community_idx IF NOT EXISTS FOR (b:Broker) ON (b.community_id)",
    "CREATE INDEX property_community_idx IF NOT EXISTS FOR (p:Property) ON (p.community_id)",
    "CREATE INDEX insight_published_idx IF NOT EXISTS FOR (i:Insight) ON (i.published_at)",
]

VECTOR_INDEXES = [
    # Node2Vec embeddings (128-dim) — populated by Phase 3 ML enricher
    """CREATE VECTOR INDEX broker_embedding_idx IF NOT EXISTS
       FOR (b:Broker) ON (b.embedding)
       OPTIONS { indexConfig: { `vector.dimensions`: 128, `vector.similarity_function`: 'cosine' } }""",
    """CREATE VECTOR INDEX property_embedding_idx IF NOT EXISTS
       FOR (p:Property) ON (p.embedding)
       OPTIONS { indexConfig: { `vector.dimensions`: 128, `vector.similarity_function`: 'cosine' } }""",
    """CREATE VECTOR INDEX tenant_embedding_idx IF NOT EXISTS
       FOR (t:Tenant) ON (t.embedding)
       OPTIONS { indexConfig: { `vector.dimensions`: 128, `vector.similarity_function`: 'cosine' } }""",
    # Insight body embeddings (384-dim) — populated by Phase 2 streaming ingester
    # using sentence-transformers all-MiniLM-L6-v2.  Different dimension from
    # Node2Vec, so a separate index is required.
    """CREATE VECTOR INDEX insight_embedding_idx IF NOT EXISTS
       FOR (i:Insight) ON (i.embedding)
       OPTIONS { indexConfig: { `vector.dimensions`: 384, `vector.similarity_function`: 'cosine' } }""",
]


def get_driver() -> Driver:
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "hackathon_local_only")
    return GraphDatabase.driver(uri, auth=(user, password))


def bootstrap_schema(driver: Driver) -> None:
    """
    Create all constraints and indexes idempotently.
    Must be called before any MERGE operations.
    Vector indexes are attempted but failures are logged-not-raised
    (older GDS plugin versions may not support them yet).
    """
    with driver.session() as session:
        for stmt in CONSTRAINTS:
            session.run(stmt)
        for stmt in INDEXES:
            session.run(stmt)
        for stmt in VECTOR_INDEXES:
            # N4: extract index name for actionable failure logs
            idx_name = "unknown"
            for token in stmt.split():
                if token.endswith("_idx"):
                    idx_name = token
                    break
            try:
                session.run(stmt)
            except Exception as exc:
                log.warning("vector_index_skipped", index_name=idx_name, error=str(exc))
    log.info("schema_bootstrap_done")


def _now() -> int:
    """Return current UTC epoch millis for Neo4j datetime."""
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _coerce_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _coerce_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _split_csv(val: Any) -> list[str]:
    if not val:
        return []
    return [v.strip() for v in str(val).split(",") if v.strip()]


# ---------------------------------------------------------------------------
# CRE_BROKERS upsert
# ---------------------------------------------------------------------------

BROKER_CYPHER = """
MERGE (b:Broker {broker_key: $broker_key})
SET b.name          = $name,
    b.email         = $email,
    b.phone         = $phone,
    b.firm_name     = $firm_name,
    b.markets       = $markets,
    b.specializations = $specializations,
    b.deal_volume_usd = $deal_volume_usd,
    b.certifications  = $certifications,
    b.last_seen       = datetime()
WITH b
MERGE (f:Firm {name: $firm_key})
ON CREATE SET f.display_name = $firm_name, f.last_seen = datetime()
ON MATCH  SET f.last_seen    = datetime()
MERGE (b)-[:BELONGS_TO]->(f)
RETURN b.broker_key AS key
"""

BROKER_COVERS_CYPHER = """
MATCH (b:Broker {broker_key: $broker_key})
MERGE (m:Market {name: $market_name})
ON CREATE SET m.display_name = $market_name, m.last_seen = datetime()
ON MATCH  SET m.last_seen    = datetime()
MERGE (b)-[:COVERS]->(m)
"""

BROKER_SPECIALIZES_CYPHER = """
MATCH (b:Broker {broker_key: $broker_key})
MERGE (a:AssetClass {name: $asset_class_name})
ON CREATE SET a.display_name = $asset_class_name, a.last_seen = datetime()
ON MATCH  SET a.last_seen    = datetime()
MERGE (b)-[:SPECIALIZES_IN]->(a)
"""


def upsert_broker(session: Session, row: dict, broker_key: str, taxonomy_key_fn) -> None:
    # CRE_BROKERS actual columns: PRIMARY_MARKET, SECONDARY_MARKET, SPECIALIZATION,
    # ASSET_CLASS_FOCUS, CERTIFICATION, FIRM_NAME, FULL_NAME, YTD_DEAL_VOLUME
    firm_raw = (
        row.get("FIRM_NAME") or row.get("FIRM") or row.get("firm") or ""
    ).strip()

    # Build markets list from PRIMARY_MARKET + SECONDARY_MARKET
    market_vals = []
    for field in ("PRIMARY_MARKET", "SECONDARY_MARKET", "MARKETS_CSV", "markets_csv"):
        val = (row.get(field) or "").strip()
        if val:
            market_vals.extend(_split_csv(val))
    markets = [taxonomy_key_fn(m, "markets") for m in market_vals if m]

    # Specializations: SPECIALIZATION + ASSET_CLASS_FOCUS
    spec_vals = []
    for field in ("SPECIALIZATION", "ASSET_CLASS_FOCUS", "SPECIALIZATIONS", "specializations"):
        val = (row.get(field) or "").strip()
        if val:
            spec_vals.extend(_split_csv(val))
    specs = [taxonomy_key_fn(s, "asset_classes") for s in spec_vals if s]

    # Certifications: CERTIFICATION field (comma-separated)
    certs_csv = row.get("CERTIFICATION") or row.get("CERTIFICATIONS") or row.get("certifications") or ""

    name = (
        row.get("FULL_NAME")
        or row.get("BROKER_NAME")
        or row.get("broker_name")
        or ""
    ).strip()

    session.run(
        BROKER_CYPHER,
        broker_key=broker_key,
        name=name,
        email=(row.get("EMAIL") or row.get("email") or "").strip().lower() or None,
        phone=(row.get("PHONE") or row.get("phone") or None),
        firm_name=firm_raw,
        firm_key=firm_raw.lower(),
        markets=markets,
        specializations=specs,
        deal_volume_usd=_coerce_float(row.get("YTD_DEAL_VOLUME") or row.get("ytd_deal_volume")),
        certifications=_split_csv(certs_csv),
    )

    for market in markets:
        session.run(BROKER_COVERS_CYPHER, broker_key=broker_key, market_name=market)
    for spec in specs:
        session.run(BROKER_SPECIALIZES_CYPHER, broker_key=broker_key, asset_class_name=spec)


# ---------------------------------------------------------------------------
# CRE_PROPERTIES upsert
# ---------------------------------------------------------------------------

PROPERTY_CYPHER = """
MERGE (p:Property {property_key: $property_key})
SET p.property_id         = $property_id,
    p.address_line1       = $address_line1,
    p.city                = $city,
    p.state               = $state,
    p.zip                 = $zip,
    p.size_sqft           = $size_sqft,
    p.year_built          = $year_built,
    p.occupancy_pct       = $occupancy_pct,
    p.owner_name          = $owner_name,
    p.sustainability_rating = $sustainability_rating,
    p.last_seen           = datetime()
WITH p
// Submarket + Market hierarchy
MERGE (sm:Submarket {name: $submarket_name})
ON CREATE SET sm.display_name = $submarket_name, sm.last_seen = datetime()
ON MATCH  SET sm.last_seen    = datetime()
MERGE (m:Market {name: $market_name})
ON CREATE SET m.display_name = $market_name, m.last_seen = datetime()
ON MATCH  SET m.last_seen    = datetime()
MERGE (sm)-[:PART_OF]->(m)
MERGE (p)-[:LOCATED_IN]->(sm)
WITH p
// AssetClass
MERGE (a:AssetClass {name: $asset_class_name})
ON CREATE SET a.display_name = $asset_class_name, a.last_seen = datetime()
ON MATCH  SET a.last_seen    = datetime()
MERGE (p)-[:CLASSIFIED_AS]->(a)
RETURN p.property_key AS key
"""

PROPERTY_LANDLORD_CYPHER = """
MATCH (p:Property {property_key: $property_key})
MERGE (ll:Landlord {landlord_key: $landlord_key})
ON CREATE SET ll.name = $owner_name, ll.last_seen = datetime()
ON MATCH  SET ll.last_seen = datetime()
MERGE (p)-[:OWNED_BY]->(ll)
"""


def upsert_property(session: Session, row: dict, prop_key: str, landlord_key_fn, taxonomy_key_fn) -> None:
    # CRE_PROPERTIES actual columns: OWNER_NAME, ZIP_CODE, TOTAL_BUILDING_SF,
    # PROPERTY_TYPE (=asset class), LEED_CERTIFICATION, OCCUPANCY_PCT
    owner_name = (row.get("OWNER_NAME") or row.get("OWNER") or row.get("owner") or "").strip()
    submarket_raw = (row.get("SUBMARKET") or row.get("submarket") or "").strip()
    market_raw = (row.get("MARKET") or row.get("market") or "").strip()
    # CRE_PROPERTIES uses PROPERTY_TYPE for asset class
    asset_class_raw = (
        row.get("PROPERTY_TYPE")
        or row.get("ASSET_CLASS")
        or row.get("asset_class")
        or ""
    ).strip()
    zip_val = (row.get("ZIP_CODE") or row.get("ZIP") or row.get("zip") or "").strip()
    size_sqft = _coerce_int(
        row.get("TOTAL_BUILDING_SF") or row.get("RENTABLE_SF") or row.get("SIZE_SQFT") or row.get("size_sqft")
    )
    sustainability = (
        row.get("LEED_CERTIFICATION") or row.get("LEED_RATING") or row.get("leed_rating") or None
    )
    occupancy = _coerce_float(
        row.get("OCCUPANCY_PCT") or row.get("OCCUPANCY") or row.get("occupancy")
    )

    session.run(
        PROPERTY_CYPHER,
        property_key=prop_key,
        property_id=(row.get("PROPERTY_ID") or row.get("property_id") or None),
        address_line1=(row.get("ADDRESS") or row.get("address") or "").strip(),
        city=(row.get("CITY") or row.get("city") or "").strip(),
        state=(row.get("STATE") or row.get("state") or "").strip(),
        zip=zip_val,
        size_sqft=size_sqft,
        year_built=_coerce_int(row.get("YEAR_BUILT") or row.get("year_built")),
        occupancy_pct=occupancy,
        owner_name=owner_name or None,
        sustainability_rating=sustainability,
        submarket_name=taxonomy_key_fn(submarket_raw, "submarkets") if submarket_raw else "unknown",
        market_name=taxonomy_key_fn(market_raw, "markets") if market_raw else "unknown",
        asset_class_name=taxonomy_key_fn(asset_class_raw, "asset_classes") if asset_class_raw else "unknown",
    )

    if owner_name:
        ll_key = landlord_key_fn(row)
        session.run(
            PROPERTY_LANDLORD_CYPHER,
            property_key=prop_key,
            landlord_key=ll_key,
            owner_name=owner_name,
        )


# ---------------------------------------------------------------------------
# CRE_LEASE_COMPS upsert
# ---------------------------------------------------------------------------

LEASE_CYPHER = """
MERGE (p:Property {property_key: $property_key})
ON CREATE SET p.address_line1 = $address_line1,
              p.zip            = $zip,
              p.last_seen      = datetime()
ON MATCH  SET p.last_seen      = datetime()
WITH p
MERGE (t:Tenant {tenant_key: $tenant_key})
ON CREATE SET t.name         = $tenant_name,
              t.industry     = $industry,
              t.credit_profile = $credit_profile,
              t.last_seen    = datetime()
ON MATCH  SET t.name         = $tenant_name,
              t.last_seen    = datetime()
WITH p, t
MERGE (ll:Landlord {landlord_key: $landlord_key})
ON CREATE SET ll.name = $landlord_name, ll.last_seen = datetime()
ON MATCH  SET ll.last_seen = datetime()
WITH p, t, ll
MERGE (l:Lease {lease_key: $lease_key})
ON CREATE SET l.lease_id           = $lease_id,
              l.rent_per_sqft       = $rent_per_sqft,
              l.ti_per_sqft         = $ti_per_sqft,
              l.concessions_months  = $concessions_months,
              l.term_months         = $term_months,
              l.execution_date      = $execution_date,
              l.size_sqft           = $size_sqft,
              l.last_seen           = datetime()
ON MATCH  SET l.last_seen           = datetime()
MERGE (l)-[:ON]->(p)
MERGE (l)-[:TENANT_IS]->(t)
MERGE (l)-[:LANDLORD_IS]->(ll)
RETURN l.lease_key AS key
"""

LEASE_BROKERED_CYPHER = """
MATCH (l:Lease {lease_key: $lease_key})
MERGE (b:Broker {broker_key: $broker_key})
ON CREATE SET b.name = $broker_name, b.last_seen = datetime()
ON MATCH  SET b.last_seen = datetime()
MERGE (l)-[:BROKERED_BY {side: $side}]->(b)
"""


def upsert_lease(session: Session, row: dict, l_key: str, p_key: str, t_key: str, ll_key: str, broker_key_fn, taxonomy_key_fn) -> None:
    exec_date = row.get("EXECUTION_DATE") or row.get("execution_date")
    if exec_date is not None:
        exec_date = str(exec_date)

    session.run(
        LEASE_CYPHER,
        property_key=p_key,
        address_line1=(row.get("ADDRESS") or row.get("address") or "").strip(),
        zip=(row.get("ZIP") or row.get("zip") or "").strip(),
        tenant_key=t_key,
        tenant_name=(row.get("TENANT_NAME") or row.get("tenant_name") or "").strip(),
        industry=(row.get("TENANT_INDUSTRY") or row.get("tenant_industry") or None),
        credit_profile=(row.get("TENANT_CREDIT") or row.get("tenant_credit") or None),
        landlord_key=ll_key,
        landlord_name=(row.get("LANDLORD_NAME") or row.get("landlord_name") or "").strip(),
        lease_key=l_key,
        lease_id=(row.get("LEASE_ID") or row.get("lease_id") or None),
        rent_per_sqft=_coerce_float(row.get("RENT_PSF") or row.get("rent_psf")),
        ti_per_sqft=_coerce_float(row.get("TI_PSF") or row.get("ti_psf")),
        concessions_months=_coerce_int(row.get("CONCESSIONS") or row.get("concessions")),
        term_months=_coerce_int(row.get("TERM_MONTHS") or row.get("term_months")),
        execution_date=exec_date,
        size_sqft=_coerce_int(row.get("LEASE_SQFT") or row.get("lease_sqft")),
    )

    broker_name = (row.get("BROKER_NAME") or row.get("broker_name") or "").strip()
    if broker_name:
        b_key = broker_key_fn(row)
        side = (row.get("BROKER_SIDE") or row.get("broker_side") or "both")
        session.run(
            LEASE_BROKERED_CYPHER,
            lease_key=l_key,
            broker_key=b_key,
            broker_name=broker_name,
            side=side,
        )


# ---------------------------------------------------------------------------
# CRE_PURSUITS upsert
# ---------------------------------------------------------------------------

PURSUIT_CYPHER = """
MERGE (c:Client {client_key: $client_key})
ON CREATE SET c.name = $client_name, c.last_seen = datetime()
ON MATCH  SET c.name = $client_name, c.last_seen = datetime()
WITH c
MERGE (pu:Pursuit {pursuit_id: $pursuit_id})
ON CREATE SET pu.stage                  = $stage,
              pu.probability_pct         = $probability_pct,
              pu.revenue_projection_usd  = $revenue_projection_usd,
              pu.outcome                 = $outcome,
              pu.outcome_date            = $outcome_date,
              pu.created_date            = $created_date,
              pu.last_seen               = datetime()
ON MATCH  SET pu.stage                  = $stage,
              pu.probability_pct         = $probability_pct,
              pu.last_seen               = datetime()
MERGE (pu)-[:FOR]->(c)
RETURN pu.pursuit_id AS id
"""

PURSUIT_BROKER_CYPHER = """
MATCH (pu:Pursuit {pursuit_id: $pursuit_id})
MERGE (b:Broker {broker_key: $broker_key})
ON CREATE SET b.name = $broker_name, b.last_seen = datetime()
ON MATCH  SET b.last_seen = datetime()
MERGE (pu)-[:ASSIGNED_TO {role: $role}]->(b)
"""

PURSUIT_SERVICE_LINE_CYPHER = """
MATCH (pu:Pursuit {pursuit_id: $pursuit_id})
MERGE (sl:ServiceLine {name: $service_line_name})
ON CREATE SET sl.display_name = $service_line_name, sl.last_seen = datetime()
ON MATCH  SET sl.last_seen = datetime()
MERGE (pu)-[:HAS_SERVICE_LINE]->(sl)
"""


def upsert_pursuit(session: Session, row: dict, c_key: str, broker_key_fn, taxonomy_key_fn) -> None:
    from ingester.normalizer import client_display_name  # B3: use shared fallback helper

    pursuit_id = (row.get("PURSUIT_ID") or row.get("pursuit_id") or "").strip()
    if not pursuit_id:
        log.warning("pursuit_missing_id", row_keys=list(row.keys()))
        return

    session.run(
        PURSUIT_CYPHER,
        client_key=c_key,
        client_name=client_display_name(row),  # B3: ACCOUNT_NAME → ORGANIZATION → CLIENT_NAME
        pursuit_id=pursuit_id,
        stage=(row.get("STAGE") or row.get("stage") or "").strip(),
        probability_pct=_coerce_float(row.get("PROBABILITY") or row.get("probability")),
        revenue_projection_usd=_coerce_float(row.get("REVENUE_PROJECTION") or row.get("revenue_projection")),
        outcome=(row.get("OUTCOME") or row.get("outcome") or None),
        outcome_date=str(row.get("OUTCOME_DATE") or row.get("outcome_date") or "") or None,
        created_date=str(row.get("CREATED_DATE") or row.get("created_date") or "") or None,
    )

    assigned_broker = (row.get("ASSIGNED_BROKER") or row.get("assigned_broker") or "").strip()
    if assigned_broker:
        b_key = broker_key_fn(row)
        role = (row.get("ROLE") or row.get("role") or "primary")
        session.run(
            PURSUIT_BROKER_CYPHER,
            pursuit_id=pursuit_id,
            broker_key=b_key,
            broker_name=assigned_broker,
            role=role,
        )

    service_line_raw = (row.get("SERVICE_LINE") or row.get("service_line") or "").strip()
    if service_line_raw:
        sl_name = taxonomy_key_fn(service_line_raw, "service_lines")
        session.run(
            PURSUIT_SERVICE_LINE_CYPHER,
            pursuit_id=pursuit_id,
            service_line_name=sl_name,
        )


# ---------------------------------------------------------------------------
# CRE_SPOC upsert
# ---------------------------------------------------------------------------

SPOC_CYPHER = """
MERGE (b:Broker {broker_key: $broker_key})
ON CREATE SET b.name = $broker_name, b.last_seen = datetime()
ON MATCH  SET b.last_seen = datetime()
WITH b
MERGE (c:Client {client_key: $client_key})
ON CREATE SET c.name = $client_name, c.account_type = $account_type, c.last_seen = datetime()
ON MATCH  SET c.name = $client_name, c.last_seen = datetime()
WITH b, c
MERGE (b)-[s:SPOC_FOR {service_line: $service_line, asset_class: $asset_class}]->(c)
SET s.geography      = $geography,
    s.effective_from = $effective_from,
    s.expires_on     = $expires_on,
    s.is_active      = $is_active
RETURN s.service_line AS sl
"""


def upsert_spoc(session: Session, row: dict, b_key: str, c_key: str, taxonomy_key_fn) -> None:
    from datetime import date

    expires_on_raw = row.get("EXPIRES_ON") or row.get("expires_on")
    effective_from_raw = row.get("EFFECTIVE_FROM") or row.get("effective_from")

    # Determine if SPOC is active
    is_active = True
    if expires_on_raw is not None:
        try:
            if hasattr(expires_on_raw, "date"):
                exp = expires_on_raw.date()
            else:
                from datetime import date as dt
                exp = dt.fromisoformat(str(expires_on_raw))
            is_active = exp >= date.today()
        except Exception:
            is_active = True

    service_line_raw = (row.get("SERVICE_LINE") or row.get("service_line") or "").strip()
    sl_name = taxonomy_key_fn(service_line_raw, "service_lines") if service_line_raw else "unknown"

    asset_class_raw = (row.get("ASSET_CLASS") or row.get("asset_class") or "").strip()
    ac_name = taxonomy_key_fn(asset_class_raw, "asset_classes") if asset_class_raw else None

    session.run(
        SPOC_CYPHER,
        broker_key=b_key,
        broker_name=(row.get("BROKER_NAME") or row.get("broker_name") or "").strip(),
        client_key=c_key,
        client_name=(row.get("CLIENT_NAME") or row.get("client_name") or "").strip(),
        account_type=(row.get("ACCOUNT_TYPE") or row.get("account_type") or None),
        service_line=sl_name,
        geography=(row.get("GEOGRAPHY") or row.get("geography") or None),
        asset_class=ac_name,
        effective_from=str(effective_from_raw) if effective_from_raw else None,
        expires_on=str(expires_on_raw) if expires_on_raw else None,
        is_active=is_active,
    )
