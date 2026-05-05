"""
Integration tests for ingester/graph_writer.py.

Uses testcontainers-python to spin up a real Neo4j instance.
Tests are marked with @pytest.mark.integration and skipped if Docker is unavailable.

The tests assert that:
- bootstrap_schema() creates constraints without error
- MERGE operations are idempotent (run twice, count stays the same)
- Each entity type creates the expected node label
"""

from __future__ import annotations

import pytest

try:
    from testcontainers.neo4j import Neo4jContainer
    TESTCONTAINERS_AVAILABLE = True
except ImportError:
    TESTCONTAINERS_AVAILABLE = False

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def neo4j_container():
    if not TESTCONTAINERS_AVAILABLE:
        pytest.skip("testcontainers not installed")
    with Neo4jContainer("neo4j:5.15-community").with_env(
        "NEO4J_AUTH", "neo4j/testpassword"
    ) as container:
        yield container


@pytest.fixture(scope="module")
def neo4j_driver(neo4j_container):
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(
        neo4j_container.get_connection_url(),
        auth=("neo4j", "testpassword"),
    )
    yield driver
    driver.close()


def test_bootstrap_schema_idempotent(neo4j_driver):
    from ingester.graph_writer import bootstrap_schema

    # Run twice — must not raise on second run (IF NOT EXISTS guards)
    bootstrap_schema(neo4j_driver)
    bootstrap_schema(neo4j_driver)

    with neo4j_driver.session() as session:
        result = session.run("SHOW CONSTRAINTS")
        constraints = [r["name"] for r in result]
    assert "broker_key_unique" in constraints
    assert "property_key_unique" in constraints
    assert "pursuit_id_unique" in constraints


def test_upsert_broker_idempotent(neo4j_driver):
    from ingester.graph_writer import bootstrap_schema, upsert_broker
    from ingester.normalizer import broker_key, taxonomy_key

    bootstrap_schema(neo4j_driver)

    row = {
        "BROKER_NAME": "Jane Liu",
        "EMAIL": "jane@cbre.com",
        "FIRM": "CBRE",
        "MARKETS_CSV": "DFW, Chicago",
        "SPECIALIZATIONS": "Industrial, Office",
        "YTD_DEAL_VOLUME": "145000000",
        "CERTIFICATIONS": "CCIM",
    }
    bk = broker_key(row)

    with neo4j_driver.session() as session:
        upsert_broker(session, row, bk, taxonomy_key)
        upsert_broker(session, row, bk, taxonomy_key)  # idempotent

    with neo4j_driver.session() as session:
        result = session.run("MATCH (b:Broker {broker_key: $k}) RETURN count(b) AS cnt", k=bk)
        assert result.single()["cnt"] == 1


def test_upsert_property_idempotent(neo4j_driver):
    from ingester.graph_writer import bootstrap_schema, upsert_property
    from ingester.normalizer import property_key, landlord_key, taxonomy_key

    bootstrap_schema(neo4j_driver)

    row = {
        "PROPERTY_ID": "P-TEST-001",
        "ADDRESS": "1450 Logistics Pkwy",
        "CITY": "Dallas",
        "STATE": "TX",
        "ZIP": "75201",
        "SIZE_SQFT": "200000",
        "SUBMARKET": "DFW North",
        "MARKET": "DFW",
        "ASSET_CLASS": "Industrial",
        "OWNER": "Prologis",
    }
    pk = property_key(row)

    with neo4j_driver.session() as session:
        upsert_property(session, row, pk, landlord_key, taxonomy_key)
        upsert_property(session, row, pk, landlord_key, taxonomy_key)  # idempotent

    with neo4j_driver.session() as session:
        result = session.run("MATCH (p:Property {property_key: $k}) RETURN count(p) AS cnt", k=pk)
        assert result.single()["cnt"] == 1


def test_upsert_lease_creates_relationships(neo4j_driver):
    from ingester.graph_writer import bootstrap_schema, upsert_lease
    from ingester.normalizer import property_key, tenant_key, landlord_key, lease_key, broker_key, taxonomy_key

    bootstrap_schema(neo4j_driver)

    row = {
        "LEASE_ID": "L-TEST-001",
        "ADDRESS": "500 Commerce Blvd",
        "ZIP": "30301",
        "TENANT_NAME": "Acme Corp",
        "TENANT_INDUSTRY": "Manufacturing",
        "LANDLORD_NAME": "Blackstone RE",
        "RENT_PSF": "12.50",
        "TERM_MONTHS": "60",
        "EXECUTION_DATE": "2023-06-01",
        "LEASE_SQFT": "50000",
        "BROKER_NAME": "Tom Patel",
        "BROKER_SIDE": "tenant",
        "FIRM": "JLL",
    }
    pk = property_key(row)
    tk = tenant_key(row)
    lk = landlord_key(row)
    lsk = lease_key(row)

    with neo4j_driver.session() as session:
        upsert_lease(session, row, lsk, pk, tk, lk, broker_key, taxonomy_key)

    with neo4j_driver.session() as session:
        result = session.run(
            "MATCH (l:Lease {lease_key: $k})-[:ON]->(p:Property) RETURN count(l) AS cnt",
            k=lsk,
        )
        assert result.single()["cnt"] == 1

        result = session.run(
            "MATCH (l:Lease {lease_key: $k})-[:TENANT_IS]->(t:Tenant) RETURN t.name AS name",
            k=lsk,
        )
        assert result.single()["name"] == "Acme Corp"
