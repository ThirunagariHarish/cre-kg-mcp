"""
tests/test_embeddings.py

Unit tests for ml/embeddings.py.
Mocks the graphdatascience GDS client so no live Neo4j is required.

Asserts:
- gds.graph.project is called with GRAPH_NAME, correct node/rel projections
- gds.node2vec.write is called with locked params (128-dim, walkLength=80, etc.)
- The projection is dropped before (idempotency) and after the run
- run_embeddings returns {"status": "OK"} on happy path
- run_embeddings returns {"status": "ERROR"} when GDS raises
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import pytest

import ml.embeddings as emb_module
from ml.embeddings import (
    EMBEDDING_DIM,
    WALK_LENGTH,
    WALKS_PER_NODE,
    ITERATIONS,
    WRITE_PROPERTY,
    GRAPH_NAME,
    run_embeddings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_gds_mock():
    """Return a mock GDS client with the necessary call signatures."""
    gds = MagicMock()

    # graph.project returns (G_object, stats_dict)
    mock_G = MagicMock()
    gds.graph.project.return_value = (mock_G, {"nodeCount": 150, "relationshipCount": 400})

    # node2vec.write returns a result-like dict
    gds.node2vec.write.return_value = {"nodeCount": 150, "writeMillis": 250}

    # graph.drop succeeds silently
    gds.graph.drop.return_value = None

    return gds, mock_G


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRunEmbeddingsHappyPath:
    def test_returns_ok_status(self, mocker):
        gds_mock, mock_G = _make_gds_mock()
        mocker.patch("ml.embeddings.GraphDataScience", return_value=gds_mock)
        mocker.patch("ml.embeddings._get_driver", return_value=MagicMock())

        result = run_embeddings()

        assert result["status"] == "OK"

    def test_embedding_dimension_is_128(self, mocker):
        gds_mock, mock_G = _make_gds_mock()
        mocker.patch("ml.embeddings.GraphDataScience", return_value=gds_mock)
        mocker.patch("ml.embeddings._get_driver", return_value=MagicMock())

        run_embeddings()

        call_kwargs = gds_mock.node2vec.write.call_args
        assert call_kwargs.kwargs["embeddingDimension"] == 128

    def test_walk_length_is_80(self, mocker):
        gds_mock, mock_G = _make_gds_mock()
        mocker.patch("ml.embeddings.GraphDataScience", return_value=gds_mock)
        mocker.patch("ml.embeddings._get_driver", return_value=MagicMock())

        run_embeddings()

        call_kwargs = gds_mock.node2vec.write.call_args
        assert call_kwargs.kwargs["walkLength"] == 80

    def test_walks_per_node_is_10(self, mocker):
        gds_mock, mock_G = _make_gds_mock()
        mocker.patch("ml.embeddings.GraphDataScience", return_value=gds_mock)
        mocker.patch("ml.embeddings._get_driver", return_value=MagicMock())

        run_embeddings()

        call_kwargs = gds_mock.node2vec.write.call_args
        assert call_kwargs.kwargs["walksPerNode"] == 10

    def test_iterations_is_5(self, mocker):
        gds_mock, mock_G = _make_gds_mock()
        mocker.patch("ml.embeddings.GraphDataScience", return_value=gds_mock)
        mocker.patch("ml.embeddings._get_driver", return_value=MagicMock())

        run_embeddings()

        call_kwargs = gds_mock.node2vec.write.call_args
        assert call_kwargs.kwargs["iterations"] == 5

    def test_write_property_is_embedding(self, mocker):
        # B-P3-2 FIX: data-model.md §1 specifies 'embedding' on Broker/Property/Tenant.
        gds_mock, mock_G = _make_gds_mock()
        mocker.patch("ml.embeddings.GraphDataScience", return_value=gds_mock)
        mocker.patch("ml.embeddings._get_driver", return_value=MagicMock())

        run_embeddings()

        call_kwargs = gds_mock.node2vec.write.call_args
        assert call_kwargs.kwargs["writeProperty"] == "embedding"

    def test_graph_project_called_with_locked_graph_name(self, mocker):
        gds_mock, mock_G = _make_gds_mock()
        mocker.patch("ml.embeddings.GraphDataScience", return_value=gds_mock)
        mocker.patch("ml.embeddings._get_driver", return_value=MagicMock())

        run_embeddings()

        project_calls = gds_mock.graph.project.call_args_list
        assert len(project_calls) == 1
        assert project_calls[0].args[0] == GRAPH_NAME

    def test_node_projection_includes_broker(self, mocker):
        gds_mock, mock_G = _make_gds_mock()
        mocker.patch("ml.embeddings.GraphDataScience", return_value=gds_mock)
        mocker.patch("ml.embeddings._get_driver", return_value=MagicMock())

        run_embeddings()

        node_proj = gds_mock.graph.project.call_args.args[1]
        assert "Broker" in node_proj

    def test_node_projection_includes_property(self, mocker):
        gds_mock, mock_G = _make_gds_mock()
        mocker.patch("ml.embeddings.GraphDataScience", return_value=gds_mock)
        mocker.patch("ml.embeddings._get_driver", return_value=MagicMock())

        run_embeddings()

        node_proj = gds_mock.graph.project.call_args.args[1]
        assert "Property" in node_proj

    def test_node_projection_includes_tenant(self, mocker):
        gds_mock, mock_G = _make_gds_mock()
        mocker.patch("ml.embeddings.GraphDataScience", return_value=gds_mock)
        mocker.patch("ml.embeddings._get_driver", return_value=MagicMock())

        run_embeddings()

        node_proj = gds_mock.graph.project.call_args.args[1]
        assert "Tenant" in node_proj

    def test_projection_dropped_before_run_for_idempotency(self, mocker):
        gds_mock, mock_G = _make_gds_mock()
        mocker.patch("ml.embeddings.GraphDataScience", return_value=gds_mock)
        mocker.patch("ml.embeddings._get_driver", return_value=MagicMock())

        run_embeddings()

        # graph.drop should be called before graph.project (idempotent)
        drop_calls = gds_mock.graph.drop.call_args_list
        project_calls = gds_mock.graph.project.call_args_list
        assert len(drop_calls) >= 1  # at least pre-run drop
        assert len(project_calls) == 1

    def test_projection_dropped_after_run_to_free_memory(self, mocker):
        gds_mock, mock_G = _make_gds_mock()
        mocker.patch("ml.embeddings.GraphDataScience", return_value=gds_mock)
        mocker.patch("ml.embeddings._get_driver", return_value=MagicMock())

        run_embeddings()

        drop_calls = gds_mock.graph.drop.call_args_list
        assert len(drop_calls) >= 2  # before + after

    def test_result_contains_embedding_dim(self, mocker):
        gds_mock, mock_G = _make_gds_mock()
        mocker.patch("ml.embeddings.GraphDataScience", return_value=gds_mock)
        mocker.patch("ml.embeddings._get_driver", return_value=MagicMock())

        result = run_embeddings()

        assert result["embedding_dim"] == 128


class TestRunEmbeddingsErrorPath:
    def test_returns_error_status_on_gds_exception(self, mocker):
        gds_mock = MagicMock()
        gds_mock.graph.project.side_effect = RuntimeError("GDS unavailable")
        mocker.patch("ml.embeddings.GraphDataScience", return_value=gds_mock)
        mocker.patch("ml.embeddings._get_driver", return_value=MagicMock())

        result = run_embeddings()

        assert result["status"] == "ERROR"
        assert "error" in result

    def test_returns_error_on_node2vec_failure(self, mocker):
        gds_mock, mock_G = _make_gds_mock()
        gds_mock.node2vec.write.side_effect = RuntimeError("node2vec failed")
        mocker.patch("ml.embeddings.GraphDataScience", return_value=gds_mock)
        mocker.patch("ml.embeddings._get_driver", return_value=MagicMock())

        result = run_embeddings()

        assert result["status"] == "ERROR"


class TestLockedConstants:
    def test_embedding_dim_constant_is_128(self):
        assert EMBEDDING_DIM == 128

    def test_walk_length_constant_is_80(self):
        assert WALK_LENGTH == 80

    def test_walks_per_node_constant_is_10(self):
        assert WALKS_PER_NODE == 10

    def test_iterations_constant_is_5(self):
        assert ITERATIONS == 5

    def test_write_property_is_embedding(self):
        # B-P3-2 FIX: data-model.md §1 specifies 'embedding' on Broker/Property/Tenant.
        # Insight is NOT in the Node2Vec projection (different label), so no collision.
        # Both Node2Vec (128-dim) and sentence-transformers (384-dim) write to 'embedding'
        # but on different node labels.
        assert WRITE_PROPERTY == "embedding"
