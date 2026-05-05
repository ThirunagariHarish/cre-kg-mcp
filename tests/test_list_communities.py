"""
tests/test_list_communities.py

Unit tests for mcp_server/tools/list_communities.py.

M-P3-4: Asserts dominant_market and dominant_asset_class are returned per community.
M-P3-6: Asserts members_sample uses consistent {id, label, name} shape.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from mcp_server.tools.list_communities import run_list_communities, _node_ref


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_neo4j_node(labels, props):
    """Build a mock Neo4j node compatible with _node_ref (which calls dict(n))."""
    node = MagicMock()
    node.labels = set(labels)
    # Neo4j nodes iterate over their properties as key-value pairs
    # dict(n) calls n.keys() and n[key], so we must support that interface
    node.keys.return_value = list(props.keys())
    node.__getitem__ = lambda s, k: props[k]
    node.__iter__ = lambda s: iter(props.keys())
    # Make dict(node) work by implementing the mapping protocol
    # The Neo4j Python driver makes nodes dict-like via .items()
    node.items.return_value = list(props.items())
    return node


def _make_driver_mock(community_rows, last_run_at=None):
    """Build a mock driver that returns community_rows from the main query."""
    # Build mock row objects
    row_mocks = []
    for r in community_rows:
        row = MagicMock()
        row.__getitem__ = lambda self, key, _r=r: _r[key]
        row_mocks.append(row)

    meta_result = MagicMock()
    if last_run_at:
        meta_result.single.return_value = {"last_run_at": last_run_at}
    else:
        meta_result.single.return_value = None

    communities_result = MagicMock()
    communities_result.__iter__ = lambda s: iter(row_mocks)

    session_mock = MagicMock()
    session_mock.__enter__ = lambda s: s
    session_mock.__exit__ = MagicMock(return_value=False)

    call_count = [0]
    def _run(cypher, **kwargs):
        c = call_count[0]
        call_count[0] += 1
        if "MLRunMeta" in cypher:
            return meta_result
        else:
            return communities_result

    session_mock.run.side_effect = _run

    driver = MagicMock()
    driver.session.return_value = session_mock
    return driver


# ---------------------------------------------------------------------------
# M-P3-4: dominant_market and dominant_asset_class
# ---------------------------------------------------------------------------

class TestListCommunitiesDominantFields:
    @pytest.mark.asyncio
    async def test_dominant_market_returned_in_community(self):
        """M-P3-4: Each community entry includes dominant_market field."""
        rows = [
            {
                "cid": 7,
                "sz": 184,
                "sample_nodes": [],
                "dominant_market": "dallas-fort worth",
                "dominant_asset_class": "industrial",
            }
        ]
        driver = _make_driver_mock(rows)

        result = await run_list_communities(driver, min_size=5)

        assert result["status"] == "OK"
        assert len(result["communities"]) == 1
        community = result["communities"][0]
        assert community["dominant_market"] == "dallas-fort worth"

    @pytest.mark.asyncio
    async def test_dominant_asset_class_returned_in_community(self):
        """M-P3-4: Each community entry includes dominant_asset_class field."""
        rows = [
            {
                "cid": 7,
                "sz": 184,
                "sample_nodes": [],
                "dominant_market": "atlanta",
                "dominant_asset_class": "retail",
            }
        ]
        driver = _make_driver_mock(rows)

        result = await run_list_communities(driver, min_size=5)

        community = result["communities"][0]
        assert community["dominant_asset_class"] == "retail"

    @pytest.mark.asyncio
    async def test_dominant_fields_can_be_none(self):
        """M-P3-4: dominant_market/asset_class may be None for isolated communities."""
        rows = [
            {
                "cid": 3,
                "sz": 12,
                "sample_nodes": [],
                "dominant_market": None,
                "dominant_asset_class": None,
            }
        ]
        driver = _make_driver_mock(rows)

        result = await run_list_communities(driver, min_size=5)

        community = result["communities"][0]
        assert community["dominant_market"] is None
        assert community["dominant_asset_class"] is None

    @pytest.mark.asyncio
    async def test_multiple_communities_all_have_dominant_fields(self):
        """M-P3-4: All communities in the list have the dominant fields."""
        rows = [
            {"cid": 1, "sz": 100, "sample_nodes": [], "dominant_market": "chicago", "dominant_asset_class": "office"},
            {"cid": 2, "sz": 80, "sample_nodes": [], "dominant_market": "houston", "dominant_asset_class": "industrial"},
        ]
        driver = _make_driver_mock(rows)

        result = await run_list_communities(driver, min_size=5)

        assert len(result["communities"]) == 2
        for comm in result["communities"]:
            assert "dominant_market" in comm
            assert "dominant_asset_class" in comm


# ---------------------------------------------------------------------------
# M-P3-6: consistent {id, label, name} shape
# ---------------------------------------------------------------------------

class TestListCommunitiesMemberShape:
    def test_node_ref_broker_returns_correct_shape(self):
        """M-P3-6: _node_ref always returns {id, label, name}."""
        node = _make_neo4j_node(["Broker"], {
            "broker_key": "email::jane@cbre.com",
            "name": "Jane Liu",
        })
        result = _node_ref(node)

        assert result["id"] == "email::jane@cbre.com"
        assert result["label"] == "Broker"
        assert result["name"] == "Jane Liu"

    def test_node_ref_property_returns_address_as_name(self):
        """M-P3-6: Property nodes use address_line1 as name."""
        node = _make_neo4j_node(["Property"], {
            "property_key": "id::P-1234",
            "address_line1": "1450 Logistics Pkwy",
        })
        result = _node_ref(node)

        assert result["id"] == "id::P-1234"
        assert result["label"] == "Property"
        assert result["name"] == "1450 Logistics Pkwy"

    def test_node_ref_tenant_returns_name(self):
        """M-P3-6: Tenant nodes return .name property."""
        node = _make_neo4j_node(["Tenant"], {
            "tenant_key": "name::acme corp",
            "name": "Acme Corp",
        })
        result = _node_ref(node)

        assert result["id"] == "name::acme corp"
        assert result["label"] == "Tenant"
        assert result["name"] == "Acme Corp"

    def test_node_ref_result_always_has_three_keys(self):
        """M-P3-6: _node_ref always returns exactly {id, label, name}."""
        node = _make_neo4j_node(["Broker"], {"broker_key": "key::xyz", "name": "Test"})
        result = _node_ref(node)

        assert set(result.keys()) == {"id", "label", "name"}

    @pytest.mark.asyncio
    async def test_members_sample_has_id_label_name_shape(self):
        """M-P3-6: members_sample dicts have consistent {id, label, name} shape."""
        broker_node = _make_neo4j_node(["Broker"], {
            "broker_key": "email::tom@jll.com",
            "name": "Tom Patel",
        })
        rows = [
            {
                "cid": 7,
                "sz": 50,
                "sample_nodes": [broker_node],
                "dominant_market": "boston",
                "dominant_asset_class": "office",
            }
        ]
        driver = _make_driver_mock(rows)

        result = await run_list_communities(driver, min_size=5, include_members_sample=True)

        community = result["communities"][0]
        assert "members_sample" in community
        member = community["members_sample"][0]
        assert "id" in member
        assert "label" in member
        assert "name" in member
        assert member["name"] == "Tom Patel"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestListCommunitiesEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_result_returns_degraded(self):
        """Empty community list returns DEGRADED status."""
        driver = _make_driver_mock([])

        result = await run_list_communities(driver, min_size=5)

        assert result["status"] == "DEGRADED"
        assert result["communities"] == []

    @pytest.mark.asyncio
    async def test_no_members_sample_when_include_false(self):
        """members_sample not included when include_members_sample=False."""
        rows = [
            {
                "cid": 1,
                "sz": 10,
                "sample_nodes": [],
                "dominant_market": "miami",
                "dominant_asset_class": "multifamily",
            }
        ]
        driver = _make_driver_mock(rows)

        result = await run_list_communities(driver, min_size=5, include_members_sample=False)

        community = result["communities"][0]
        assert "members_sample" not in community

    @pytest.mark.asyncio
    async def test_computed_at_populated_from_ml_meta(self):
        """computed_at is populated from MLRunMeta when available."""
        rows = [
            {"cid": 1, "sz": 10, "sample_nodes": [], "dominant_market": None, "dominant_asset_class": None}
        ]
        driver = _make_driver_mock(rows, last_run_at="2026-05-05T14:32:11Z")

        result = await run_list_communities(driver, min_size=5)

        assert result["computed_at"] is not None
        assert "2026-05-05" in str(result["computed_at"])
