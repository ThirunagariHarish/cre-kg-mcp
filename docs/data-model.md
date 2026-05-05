# CRE Knowledge Graph — Data Model

This document defines:
1. Neo4j node labels with property types
2. Relationship types with properties
3. Constraints and indexes (including vector index)
4. Snowflake table → graph entity mapping with merge keys

All MERGE operations are idempotent. Every node carries `last_seen: datetime` updated on every ingest pass; stale-detection queries can use this.

---

## 1. Node Labels

### `:Broker`
| Property | Type | Source | Notes |
|---|---|---|---|
| broker_key | string | derived | merge key (see §4.1) |
| name | string | CRE_BROKERS.broker_name | |
| email | string? | CRE_BROKERS.email | nullable |
| phone | string? | CRE_BROKERS.phone | |
| firm_name | string | CRE_BROKERS.firm | also drives `:Firm` node |
| markets | list<string> | CRE_BROKERS.markets_csv | denormalized for quick filter |
| specializations | list<string> | CRE_BROKERS.specializations | |
| deal_volume_usd | float | CRE_BROKERS.ytd_deal_volume | |
| certifications | list<string> | CRE_BROKERS.certifications | |
| embedding | list<float> | ML | 128-dim, written by Node2Vec |
| community_id | int | ML | written by Louvain |
| last_seen | datetime | ingester | |

### `:Property`
| Property | Type | Source | Notes |
|---|---|---|---|
| property_key | string | derived | merge key (§4.1) |
| property_id | string? | CRE_PROPERTIES.property_id | source PK if present |
| address_line1 | string | CRE_PROPERTIES.address | |
| city | string | CRE_PROPERTIES.city | |
| state | string | CRE_PROPERTIES.state | |
| zip | string | CRE_PROPERTIES.zip | |
| size_sqft | int | CRE_PROPERTIES.size_sqft | |
| year_built | int? | CRE_PROPERTIES.year_built | |
| occupancy_pct | float? | CRE_PROPERTIES.occupancy | |
| owner_name | string? | CRE_PROPERTIES.owner | drives `:Landlord` |
| sustainability_rating | string? | CRE_PROPERTIES.leed_rating | |
| financials_json | string? | CRE_PROPERTIES.financials | raw JSON |
| embedding | list<float> | ML | |
| community_id | int | ML | |
| last_seen | datetime | ingester | |

### `:Tenant`
| Property | Type | Source |
|---|---|---|
| tenant_key | string | derived |
| name | string | CRE_LEASE_COMPS.tenant_name |
| industry | string? | CRE_LEASE_COMPS.tenant_industry |
| credit_profile | string? | CRE_LEASE_COMPS.tenant_credit |
| embedding | list<float> | ML |
| community_id | int | ML |
| last_seen | datetime | ingester |

### `:Landlord`
| Property | Type | Source |
|---|---|---|
| landlord_key | string | derived |
| name | string | CRE_LEASE_COMPS.landlord_name / CRE_PROPERTIES.owner |
| portfolio_size | int? | derived |
| last_seen | datetime | ingester |

### `:Lease`
| Property | Type | Source |
|---|---|---|
| lease_key | string | derived |
| lease_id | string? | CRE_LEASE_COMPS.lease_id |
| rent_per_sqft | float | CRE_LEASE_COMPS.rent_psf |
| ti_per_sqft | float? | CRE_LEASE_COMPS.ti_psf |
| concessions_months | int? | CRE_LEASE_COMPS.concessions |
| term_months | int | CRE_LEASE_COMPS.term_months |
| execution_date | date | CRE_LEASE_COMPS.execution_date |
| size_sqft | int | CRE_LEASE_COMPS.lease_sqft |
| last_seen | datetime | ingester |

### `:Pursuit`
| Property | Type | Source |
|---|---|---|
| pursuit_id | string | CRE_PURSUITS.pursuit_id (PK) |
| stage | string | CRE_PURSUITS.stage |
| probability_pct | float | CRE_PURSUITS.probability |
| revenue_projection_usd | float | CRE_PURSUITS.revenue_projection |
| outcome | string? | CRE_PURSUITS.outcome |
| outcome_date | date? | CRE_PURSUITS.outcome_date |
| created_date | date | CRE_PURSUITS.created_date |
| last_seen | datetime | ingester |

### `:Client`
| Property | Type | Source |
|---|---|---|
| client_key | string | derived |
| name | string | CRE_PURSUITS.client_name / CRE_SPOC.client_name |
| account_type | string? | CRE_SPOC.account_type |
| last_seen | datetime | ingester |

### `:Market` / `:Submarket` / `:AssetClass` / `:ServiceLine` / `:Firm`
Taxonomy nodes, all share the same shape:
| Property | Type |
|---|---|
| name | string (canonical, lowercase trimmed) |
| display_name | string (preferred display form) |
| last_seen | datetime |

### `:Insight`
| Property | Type | Source |
|---|---|---|
| insight_id | string | source PK |
| title | string | source |
| body | string | source |
| source | string | source |
| published_at | datetime | source |
| ingested_at | datetime | ingester |
| raw_tags | list<string> | source |
| sentiment | string? | source |
| embedding | list<float> | ML |
| last_seen | datetime | ingester |

### `:Community` (synthetic)
| Property | Type |
|---|---|
| community_id | int |
| size | int |
| dominant_market | string? |
| dominant_asset_class | string? |
| computed_at | datetime |

---

## 2. Relationship Types

| Type | From → To | Properties |
|---|---|---|
| `:BELONGS_TO` | Broker → Firm | — |
| `:COVERS` | Broker → Market | `since: date?` |
| `:SPECIALIZES_IN` | Broker → AssetClass | — |
| `:REPRESENTS` | Broker → Client | — |
| `:SPOC_FOR` | Broker → Client | `service_line: string`, `geography: string?`, `asset_class: string?`, `effective_from: date`, `expires_on: date?`, `is_active: bool` |
| `:FOR` | Pursuit → Client | — |
| `:ASSIGNED_TO` | Pursuit → Broker | `role: string` |
| `:HAS_SERVICE_LINE` | Pursuit → ServiceLine | — |
| `:ON` | Lease → Property | — |
| `:TENANT_IS` | Lease → Tenant | — |
| `:LANDLORD_IS` | Lease → Landlord | — |
| `:BROKERED_BY` | Lease → Broker | `side: 'tenant'\|'landlord'\|'both'` |
| `:LOCATED_IN` | Property → Submarket | — |
| `:PART_OF` | Submarket → Market | — |
| `:CLASSIFIED_AS` | Property → AssetClass | — |
| `:OWNED_BY` | Property → Landlord | — |
| `:ABOUT` | Insight → Market \| AssetClass \| Property \| Tenant \| Submarket | `confidence: float?` |
| `:SIMILAR_TO` (ML) | Broker ↔ Broker / Property ↔ Property | `score: float`, `computed_at: datetime` |
| `:PREDICTED_AFFINITY` (ML) | Broker → Property / Broker → Tenant | `score: float`, `model_version: string`, `computed_at: datetime` |
| `:IN_COMMUNITY` (ML) | Broker / Property / Tenant → Community | — |

---

## 3. Constraints and Indexes

### Uniqueness constraints (also implicit indexes)
```cypher
CREATE CONSTRAINT broker_key_unique IF NOT EXISTS FOR (b:Broker) REQUIRE b.broker_key IS UNIQUE;
CREATE CONSTRAINT property_key_unique IF NOT EXISTS FOR (p:Property) REQUIRE p.property_key IS UNIQUE;
CREATE CONSTRAINT tenant_key_unique IF NOT EXISTS FOR (t:Tenant) REQUIRE t.tenant_key IS UNIQUE;
CREATE CONSTRAINT landlord_key_unique IF NOT EXISTS FOR (l:Landlord) REQUIRE l.landlord_key IS UNIQUE;
CREATE CONSTRAINT lease_key_unique IF NOT EXISTS FOR (l:Lease) REQUIRE l.lease_key IS UNIQUE;
CREATE CONSTRAINT pursuit_id_unique IF NOT EXISTS FOR (p:Pursuit) REQUIRE p.pursuit_id IS UNIQUE;
CREATE CONSTRAINT client_key_unique IF NOT EXISTS FOR (c:Client) REQUIRE c.client_key IS UNIQUE;
CREATE CONSTRAINT market_name_unique IF NOT EXISTS FOR (m:Market) REQUIRE m.name IS UNIQUE;
CREATE CONSTRAINT submarket_name_unique IF NOT EXISTS FOR (s:Submarket) REQUIRE s.name IS UNIQUE;
CREATE CONSTRAINT asset_class_name_unique IF NOT EXISTS FOR (a:AssetClass) REQUIRE a.name IS UNIQUE;
CREATE CONSTRAINT service_line_name_unique IF NOT EXISTS FOR (s:ServiceLine) REQUIRE s.name IS UNIQUE;
CREATE CONSTRAINT firm_name_unique IF NOT EXISTS FOR (f:Firm) REQUIRE f.name IS UNIQUE;
CREATE CONSTRAINT insight_id_unique IF NOT EXISTS FOR (i:Insight) REQUIRE i.insight_id IS UNIQUE;
CREATE CONSTRAINT community_id_unique IF NOT EXISTS FOR (c:Community) REQUIRE c.community_id IS UNIQUE;
```

### Range / lookup indexes
```cypher
CREATE INDEX broker_name_idx IF NOT EXISTS FOR (b:Broker) ON (b.name);
CREATE INDEX property_city_state_idx IF NOT EXISTS FOR (p:Property) ON (p.city, p.state);
CREATE INDEX pursuit_stage_idx IF NOT EXISTS FOR (p:Pursuit) ON (p.stage);
CREATE INDEX lease_execution_idx IF NOT EXISTS FOR (l:Lease) ON (l.execution_date);
CREATE INDEX broker_community_idx IF NOT EXISTS FOR (b:Broker) ON (b.community_id);
CREATE INDEX property_community_idx IF NOT EXISTS FOR (p:Property) ON (p.community_id);
CREATE INDEX insight_published_idx IF NOT EXISTS FOR (i:Insight) ON (i.published_at);
```

### Vector indexes (Neo4j 5.11+)
```cypher
CREATE VECTOR INDEX broker_embedding_idx IF NOT EXISTS
  FOR (b:Broker) ON (b.embedding)
  OPTIONS { indexConfig: { `vector.dimensions`: 128, `vector.similarity_function`: 'cosine' } };

CREATE VECTOR INDEX property_embedding_idx IF NOT EXISTS
  FOR (p:Property) ON (p.embedding)
  OPTIONS { indexConfig: { `vector.dimensions`: 128, `vector.similarity_function`: 'cosine' } };

CREATE VECTOR INDEX tenant_embedding_idx IF NOT EXISTS
  FOR (t:Tenant) ON (t.embedding)
  OPTIONS { indexConfig: { `vector.dimensions`: 128, `vector.similarity_function`: 'cosine' } };

CREATE VECTOR INDEX insight_embedding_idx IF NOT EXISTS
  FOR (i:Insight) ON (i.embedding)
  OPTIONS { indexConfig: { `vector.dimensions`: 128, `vector.similarity_function`: 'cosine' } };
```

---

## 4. Snowflake → Graph Mapping

### 4.1 Merge key derivation

```python
# Pseudocode — implementation lives in ingester/normalizer.py
def broker_key(row):
    if row.email:
        return f"email::{row.email.strip().lower()}"
    return f"name::{row.broker_name.strip().lower()}::firm::{row.firm.strip().lower()}"

def property_key(row):
    if row.property_id:
        return f"id::{row.property_id}"
    addr = re.sub(r"\s+", " ", row.address.strip().lower())
    addr = re.sub(r"\b(suite|ste|unit|#)\s*\S+", "", addr)
    return f"addr::{addr}::zip::{row.zip}"

def tenant_key(row):
    return f"name::{row.tenant_name.strip().lower()}"

def landlord_key(row):
    return f"name::{row.landlord_name.strip().lower()}"

def lease_key(row):
    if row.lease_id:
        return f"id::{row.lease_id}"
    return f"prop::{property_key(row)}::tenant::{tenant_key(row)}::date::{row.execution_date}"

def client_key(row):
    return f"name::{row.client_name.strip().lower()}"

def taxonomy_key(value, kind):
    canon = canonical_map[kind].get(value.strip().lower(), value.strip().lower())
    return canon
```

### 4.2 Per-table mapping

#### `CRE_BROKERS` → `:Broker` + `:Firm` + `:Market` + `:AssetClass`
```
Row → MERGE (b:Broker {broker_key: broker_key(row)})
       SET b.name=…, b.email=…, b.deal_volume_usd=…, b.last_seen=now
   → MERGE (f:Firm {name: lower(row.firm)}) SET f.display_name=row.firm
   → MERGE (b)-[:BELONGS_TO]->(f)
   → FOR each market in row.markets_csv:
       MERGE (m:Market {name: taxonomy_key(market,'markets')})
       MERGE (b)-[:COVERS]->(m)
   → FOR each asset_class in row.specializations:
       MERGE (a:AssetClass {name: taxonomy_key(asset_class,'asset_classes')})
       MERGE (b)-[:SPECIALIZES_IN]->(a)
```

#### `CRE_PROPERTIES` → `:Property` + `:Submarket` + `:Market` + `:AssetClass` + `:Landlord`
```
Row → MERGE (p:Property {property_key: property_key(row)})
       SET p.address_line1=…, p.size_sqft=…, p.last_seen=now
   → MERGE (sm:Submarket {name: taxonomy_key(row.submarket,'submarkets')})
   → MERGE (m:Market {name: taxonomy_key(row.market,'markets')})
   → MERGE (sm)-[:PART_OF]->(m)
   → MERGE (p)-[:LOCATED_IN]->(sm)
   → MERGE (a:AssetClass {name: taxonomy_key(row.asset_class,'asset_classes')})
   → MERGE (p)-[:CLASSIFIED_AS]->(a)
   → IF row.owner: MERGE (ll:Landlord {landlord_key: landlord_key(row)}) SET ll.name=row.owner
       MERGE (p)-[:OWNED_BY]->(ll)
```

#### `CRE_LEASE_COMPS` → `:Lease` + `:Property` (link) + `:Tenant` + `:Landlord` + `:Broker` (link)
```
Row → MERGE (p:Property {property_key: property_key(row)})  # may already exist from CRE_PROPERTIES
       ON CREATE SET p.address_line1=row.address (and other fields if present)
   → MERGE (t:Tenant {tenant_key: tenant_key(row)}) SET t.name=…, t.industry=…
   → MERGE (ll:Landlord {landlord_key: landlord_key(row)}) SET ll.name=…
   → MERGE (l:Lease {lease_key: lease_key(row)})
       SET l.rent_per_sqft=…, l.term_months=…, l.execution_date=…, l.last_seen=now
   → MERGE (l)-[:ON]->(p)
   → MERGE (l)-[:TENANT_IS]->(t)
   → MERGE (l)-[:LANDLORD_IS]->(ll)
   → IF row.broker_name: MERGE (b:Broker {broker_key: broker_key(row)})
       MERGE (l)-[:BROKERED_BY {side: row.broker_side}]->(b)
```
**Cross-table dedup note:** if a Property is created first by CRE_LEASE_COMPS (only address available, no property_id), and CRE_PROPERTIES later provides a property_id, the merge key changes. We resolve this by running CRE_PROPERTIES *before* CRE_LEASE_COMPS in the backfill order, ensuring property_id-keyed nodes exist first; lease-comp rows then match the same `property_key`.

**Backfill order (locked):** CRE_BROKERS → CRE_PROPERTIES → CRE_LEASE_COMPS → CRE_PURSUITS → CRE_SPOC.

#### `CRE_PURSUITS` → `:Pursuit` + `:Client` + `:Broker` (link) + `:ServiceLine`
```
Row → MERGE (c:Client {client_key: client_key(row)}) SET c.name=row.client_name
   → MERGE (pu:Pursuit {pursuit_id: row.pursuit_id})
       SET pu.stage=…, pu.probability_pct=…, pu.revenue_projection_usd=…, pu.last_seen=now
   → MERGE (pu)-[:FOR]->(c)
   → IF row.assigned_broker:
       MERGE (b:Broker {broker_key: broker_key_from_pursuit(row)})
       MERGE (pu)-[:ASSIGNED_TO {role: row.role}]->(b)
   → IF row.service_line:
       MERGE (sl:ServiceLine {name: taxonomy_key(row.service_line,'service_lines')})
       MERGE (pu)-[:HAS_SERVICE_LINE]->(sl)
```

#### `CRE_SPOC` → `:SPOC_FOR` edges (Broker → Client) + supporting nodes
```
Row → MERGE (b:Broker {broker_key: broker_key_from_spoc(row)})
   → MERGE (c:Client {client_key: client_key(row)})
   → MERGE (b)-[s:SPOC_FOR {service_line: row.service_line}]->(c)
       SET s.geography=…, s.asset_class=…, s.effective_from=…, s.expires_on=…,
           s.is_active = (row.expires_on IS NULL OR row.expires_on > current_date)
```

### 4.3 Streaming `CRE_INSIGHTS_RAW` → `:Insight` + `ABOUT` edges

Source table assumed to exist or to be created in Phase 2:
```
CRE_INSIGHTS_RAW (
  insight_id STRING PRIMARY KEY,
  title STRING,
  body STRING,
  source STRING,
  published_at TIMESTAMP_NTZ,
  raw_tags ARRAY,
  sentiment STRING,
  inserted_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP
)
```

Stream + Task (created in Phase 2):
```sql
CREATE OR REPLACE STREAM HACKATHON.PUBLIC.CRE_INSIGHTS_STREAM
  ON TABLE HACKATHON.PUBLIC.CRE_INSIGHTS_RAW
  APPEND_ONLY = TRUE;

CREATE OR REPLACE TABLE HACKATHON.PUBLIC.CRE_INSIGHTS_DELTA AS
  SELECT *, FALSE AS processed FROM HACKATHON.PUBLIC.CRE_INSIGHTS_RAW WHERE 1=0;

CREATE OR REPLACE TASK HACKATHON.PUBLIC.CRE_INSIGHTS_TASK
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = '5 MINUTE'
AS
  INSERT INTO HACKATHON.PUBLIC.CRE_INSIGHTS_DELTA
  SELECT insight_id, title, body, source, published_at, raw_tags, sentiment, inserted_at, FALSE
  FROM HACKATHON.PUBLIC.CRE_INSIGHTS_STREAM;

ALTER TASK HACKATHON.PUBLIC.CRE_INSIGHTS_TASK RESUME;
```

Ingester polls `CRE_INSIGHTS_DELTA WHERE processed = FALSE`, processes, then UPDATE.

```
Row → MERGE (i:Insight {insight_id: row.insight_id})
       SET i.title=…, i.body=…, i.published_at=…, i.raw_tags=…, i.ingested_at=now
   → FOR each tag in row.raw_tags:
       resolved = canonical_resolver(tag)  # returns (label, name) or None
       IF resolved:
         MATCH (n:{label} {name: resolved.name}) MERGE (i)-[:ABOUT]->(n)
       ELSE:
         log_warning(unmapped_tag=tag, insight_id=row.insight_id)
```

---

## 5. Field-Level Sensitivity (hackathon stance)

| Field | Sensitivity | Hackathon handling | Production note |
|---|---|---|---|
| Broker.email, Broker.phone | PII | stored as-is | Mask in MCP tool responses |
| Client.name | Confidential | stored as-is | Tenant-scoped access required |
| Lease.rent_per_sqft | Commercially sensitive | stored as-is | Restrict to authorized brokers |
| Insight.body | May reference embargoed info | stored as-is | Apply source-level access control |
| Pursuit.revenue_projection_usd | Internal forecast | stored as-is | Restrict by service line |

All flagged but unaddressed for v1 hackathon scope per PRD §3 Non-Goals.

---

## 6. Estimated Volumes (sanity)

| Label | Estimated count |
|---|---|
| Broker | 1K–5K |
| Property | 50K–200K |
| Tenant | 20K–80K |
| Landlord | 5K–20K |
| Lease | 100K–400K |
| Pursuit | 2K–10K |
| Client | 1K–5K |
| Insight | 1K–10K (over hackathon window) |
| Total nodes | ~200K–700K (within stated 100K–500K range with light overflow) |
| Total edges | ~1M–4M |

Single Neo4j instance with `NEO4J_dbms_memory_heap_max__size=4G` and `NEO4J_dbms_memory_pagecache_size=2G` is sufficient.
