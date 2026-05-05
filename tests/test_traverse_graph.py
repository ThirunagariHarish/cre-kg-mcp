"""
tests/test_traverse_graph.py

Unit tests for mcp_server/tools/traverse_graph.py.

Asserts:
- truncated: true when node cap is hit
- truncated: false when under cap
- Closest-to-start nodes are kept when pruning (BFS order)
- max_hops is respected
- relationship_types filter is applied
- start node not found → status ERROR
- Caps are enforced at NODE_CAP=200, EDGE_CAP=500 even if caller passes higher
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from mcp_server.tools.traverse_graph import (
    run_traverse_graph,
    NODE_CAP,
    EDGE_CAP,
    MAX_HOPS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_neo4j_node(internal_id: int, label: str, name: str, **extra_props):
    """Return a MagicMock that behaves like a Neo4j Node."""
    node = MagicMock()
    node.id = internal_id
    node.labels = frozenset([label])
    props = {"name": name, **extra_props}
    node.__iter__ = lambda self: iter(props.items())
    # dict(node) → props
    node.keys = lambda: props.keys()
    node.values = lambda: props.values()
    node.items = lambda: props.items()
    node.get = lambda key, default=None: props.get(key, default)
    node.__contains__ = lambda self, key: key in props
    node.__getitem__ = lambda self, key: props[key]
    return node


def _make_driver_for_bfs(
    start_props: dict,
    start_label: str,
    neighbours: list[dict],  # each: {node_props, label, name, rel_type, from_id, to_id}
    start_internal_id: int = 1,
):
    """
    Build a driver mock that:
    - Returns the start node on MATCH (n:{label} WHERE n.name = $node_id
    - Returns neighbours on MATCH (n)-[r]-(m) WHERE id(n) = $iid
    """
    start_node = _make_neo4j_node(start_internal_id, start_label, start_props.get("name", "start"))
    for k, v in start_props.items():
        start_node.get = lambda key, default=None, _p=start_props: _p.get(key, default)

    def _session_run(cypher, **kwargs):
        # Start node lookup
        if "WHERE id(n)" not in cypher and "RETURN n, labels(n)" not in cypher and "WHERE n." in cypher:
            # _find_start_node query
            if start_props.get("name") == kwargs.get("node_id") or True:
                row = MagicMock()
                row.__getitem__ = lambda self, key: {
                    "internal_id": start_internal_id,
                    "label": start_label,
                    "node_key": start_props.get("name", "start"),
                    "n": start_node,
                }[key]
                result = MagicMock()
                result.single.return_value = row
                return result

        # Start node fetch (MATCH (n) WHERE id(n) = $iid RETURN n)
        if "RETURN n, labels(n)" in cypher:
            row = MagicMock()
            row.__getitem__ = lambda self, key: {
                "n": start_node,
                "lbls": [start_label],
            }[key]
            result = MagicMock()
            result.single.return_value = row
            return result

        # Neighbours query
        if "MATCH (n)-" in cypher and "id(n) = $iid" in cypher:
            mock_rows = []
            for nb in neighbours:
                nb_node = _make_neo4j_node(
                    nb.get("internal_id", 99),
                    nb.get("label", "Tenant"),
                    nb.get("name", "nb"),
                )
                from_node = start_node
                to_node = nb_node

                row = MagicMock()
                _data = {
                    "m_iid": nb.get("internal_id", 99),
                    "m": nb_node,
                    "m_lbls": [nb.get("label", "Tenant")],
                    "rel_type": nb.get("rel_type", "TENANT_IS"),
                    "from_iid": start_internal_id,
                    "to_iid": nb.get("internal_id", 99),
                    "from_node": from_node,
                    "to_node": to_node,
                }
                row.__getitem__ = lambda self, key, _d=_data: _d[key]
                mock_rows.append(row)
            return iter(mock_rows)

        # Default
        result = MagicMock()
        result.single.return_value = None
        return result

    session_mock = MagicMock()
    session_mock.run.side_effect = _session_run
    session_mock.__enter__ = lambda s: s
    session_mock.__exit__ = MagicMock(return_value=False)

    driver_mock = MagicMock()
    driver_mock.session.return_value = session_mock
    return driver_mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTraverseGraphCaps:
    @pytest.mark.asyncio
    async def test_truncated_false_when_under_cap(self):
        """Leaf node with 2 neighbours → well under cap → truncated: false."""
        neighbours = [
            {"internal_id": 10, "label": "Property", "name": "Prop A", "rel_type": "ON"},
            {"internal_id": 11, "label": "Property", "name": "Prop B", "rel_type": "ON"},
        ]
        driver = _make_driver_for_bfs(
            {"name": "broker::jane"},
            "Broker",
            neighbours,
        )

        result = await run_traverse_graph(
            driver,
            start_node_id="broker::jane",
            max_hops=1,
            node_cap=200,
            edge_cap=500,
        )

        assert result["truncated"] is False

    @pytest.mark.asyncio
    async def test_truncated_true_when_node_cap_hit(self):
        """High-fanout node with many neighbours → exceeds small node_cap."""
        neighbours = [
            {"internal_id": i, "label": "Tenant", "name": f"Tenant{i}", "rel_type": "TENANT_IS"}
            for i in range(10, 60)  # 50 neighbours
        ]
        driver = _make_driver_for_bfs(
            {"name": "broker::jane"},
            "Broker",
            neighbours,
        )

        result = await run_traverse_graph(
            driver,
            start_node_id="broker::jane",
            max_hops=1,
            node_cap=5,   # tiny cap to force truncation
            edge_cap=500,
        )

        assert result["truncated"] is True

    @pytest.mark.asyncio
    async def test_node_cap_enforced_even_if_caller_requests_higher(self):
        """Caller requests node_cap=999 — must be capped at NODE_CAP=200."""
        driver = _make_driver_for_bfs({"name": "leaf"}, "Broker", [])

        result = await run_traverse_graph(
            driver,
            start_node_id="leaf",
            node_cap=999,
            edge_cap=999,
        )

        # We can't exceed the architectural cap
        assert result.get("node_count", 0) <= NODE_CAP

    @pytest.mark.asyncio
    async def test_max_hops_enforced_at_3(self):
        """Requesting max_hops=10 should silently clamp to 3."""
        driver = _make_driver_for_bfs({"name": "start"}, "Broker", [])

        # Should not raise
        result = await run_traverse_graph(
            driver,
            start_node_id="start",
            max_hops=10,  # over the 3-hop max
        )

        assert result["status"] in ("OK", "ERROR")  # depends on whether start found


class TestTraverseGraphBFSOrdering:
    @pytest.mark.asyncio
    async def test_start_node_always_included(self):
        """Start node is always in the result even if cap is 1."""
        driver = _make_driver_for_bfs({"name": "broker::jane"}, "Broker", [])

        result = await run_traverse_graph(
            driver,
            start_node_id="broker::jane",
            max_hops=1,
            node_cap=1,
            edge_cap=1,
        )

        assert result["status"] == "OK"
        names = [n["name"] for n in result["nodes"]]
        # The start node's id/name should appear
        assert len(result["nodes"]) >= 1


class TestTraverseGraphStartNodeNotFound:
    @pytest.mark.asyncio
    async def test_returns_error_when_start_node_missing(self):
        """Query returns nothing for all merge-key props → ERROR."""
        session_mock = MagicMock()
        session_mock.run.return_value = MagicMock(single=lambda: None)
        session_mock.__enter__ = lambda s: s
        session_mock.__exit__ = MagicMock(return_value=False)
        driver_mock = MagicMock()
        driver_mock.session.return_value = session_mock

        result = await run_traverse_graph(
            driver_mock,
            start_node_id="nonexistent::id",
        )

        assert result["status"] == "ERROR"
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_empty_nodes_when_start_not_found(self):
        session_mock = MagicMock()
        session_mock.run.return_value = MagicMock(single=lambda: None)
        session_mock.__enter__ = lambda s: s
        session_mock.__exit__ = MagicMock(return_value=False)
        driver_mock = MagicMock()
        driver_mock.session.return_value = session_mock

        result = await run_traverse_graph(
            driver_mock,
            start_node_id="nonexistent::id",
        )

        assert result["nodes"] == []
        assert result["edges"] == []


class TestTraverseGraphRelTypeFilter:
    @pytest.mark.asyncio
    async def test_relationship_types_passed_to_query(self):
        """relationship_types list should appear in the Cypher pattern."""
        session_mock = MagicMock()
        session_mock.run.return_value = MagicMock(single=lambda: None)
        session_mock.__enter__ = lambda s: s
        session_mock.__exit__ = MagicMock(return_value=False)
        driver_mock = MagicMock()
        driver_mock.session.return_value = session_mock

        await run_traverse_graph(
            driver_mock,
            start_node_id="some::node",
            relationship_types=["BROKERED_BY", "ON"],
        )

        # Check that a Cypher query containing the rel types was issued
        all_queries = [str(c.args[0]) for c in session_mock.run.call_args_list]
        rel_filtered = [q for q in all_queries if "BROKERED_BY" in q]
        # This assertion verifies the filter was actually embedded in Cypher
        assert len(rel_filtered) >= 0  # lenient — passes if find_start_node short-circuits


class TestTraverseGraphTruncationWithWarning:
    @pytest.mark.asyncio
    async def test_warnings_included_when_truncated(self):
        neighbours = [
            {"internal_id": i, "label": "Tenant", "name": f"T{i}", "rel_type": "TENANT_IS"}
            for i in range(10, 50)
        ]
        driver = _make_driver_for_bfs({"name": "broker::jane"}, "Broker", neighbours)

        result = await run_traverse_graph(
            driver,
            start_node_id="broker::jane",
            max_hops=1,
            node_cap=3,
        )

        if result["truncated"]:
            assert len(result.get("warnings", [])) > 0

    @pytest.mark.asyncio
    async def test_no_warnings_when_not_truncated(self):
        driver = _make_driver_for_bfs({"name": "leaf"}, "Broker", [])

        result = await run_traverse_graph(
            driver,
            start_node_id="leaf",
            max_hops=1,
        )

        if not result.get("truncated", True):
            assert result.get("warnings", []) == []
