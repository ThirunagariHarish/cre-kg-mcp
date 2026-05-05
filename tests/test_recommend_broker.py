"""
Tests for mcp_server/tools/recommend_broker_for_deal.py

Verifies:
  - Active SPOC → ranked higher than same broker without SPOC
  - Expired SPOC → included with spoc_status='expired', ranked lower than active
  - No brokers found → OK with warnings (not ERROR)
  - Output shape matches api-contracts §6
  - Score ordering: active SPOC broker ranks first
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from mcp_server.tools.recommend_broker_for_deal import (
    run_recommend_broker_for_deal,
    _spoc_status_from_expiry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dict_record(d: dict) -> MagicMock:
    record = MagicMock()
    record.keys.return_value = d.keys()
    record.__iter__ = MagicMock(return_value=iter(d.keys()))
    record.__getitem__ = MagicMock(side_effect=lambda k: d.get(k))
    record.get = MagicMock(side_effect=lambda k, default=None: d.get(k, default))
    record.items.return_value = d.items()
    return record


def _make_driver(
    market_brokers: list[dict] | None = None,
    ac_brokers: list[dict] | None = None,
    spoc_map: dict[str, list[dict]] | None = None,  # broker_key → spoc rows
    affinity_map: dict[str, float] | None = None,   # broker_key → max score
    my_community: int | None = None,
):
    """
    Build a mock driver for recommend_broker_for_deal tests.
    """
    market_brokers = market_brokers or []
    ac_brokers = ac_brokers or []
    spoc_map = spoc_map or {}
    affinity_map = affinity_map or {}

    session_mock = MagicMock()

    def run_side_effect(cypher, **kwargs):
        result_mock = MagicMock()

        if "COVERS" in cypher and "Market" in cypher:
            result_mock.__iter__ = MagicMock(
                return_value=iter([_dict_record(r) for r in market_brokers])
            )
            result_mock.single.return_value = None

        elif "SPECIALIZES_IN" in cypher and "AssetClass" in cypher:
            result_mock.__iter__ = MagicMock(
                return_value=iter([_dict_record(r) for r in ac_brokers])
            )
            result_mock.single.return_value = None

        elif "SPOC_FOR" in cypher:
            bk = kwargs.get("broker_key", "")
            rows = spoc_map.get(bk, [])
            result_mock.__iter__ = MagicMock(
                return_value=iter([_dict_record(r) for r in rows])
            )
            result_mock.single.return_value = None

        elif "PredictedLink" in cypher:
            bk = kwargs.get("broker_key", "")
            max_score = affinity_map.get(bk)
            if max_score is not None:
                single_mock = MagicMock()
                single_mock.__getitem__ = MagicMock(
                    side_effect=lambda k: max_score if k == "max_score" else None
                )
                result_mock.single.return_value = single_mock
            else:
                result_mock.single.return_value = None
            result_mock.__iter__ = MagicMock(return_value=iter([]))

        elif "community_id" in cypher.lower() and "broker_key" in cypher.lower():
            if my_community is not None:
                single_mock = MagicMock()
                single_mock.__getitem__ = MagicMock(
                    side_effect=lambda k: my_community if k == "community_id" else None
                )
                result_mock.single.return_value = single_mock
            else:
                result_mock.single.return_value = None
            result_mock.__iter__ = MagicMock(return_value=iter([]))

        else:
            result_mock.single.return_value = None
            result_mock.__iter__ = MagicMock(return_value=iter([]))

        return result_mock

    session_mock.run.side_effect = run_side_effect
    driver = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session_mock)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------

class TestSpocStatusFromExpiry:
    def test_none_expiry_is_active(self):
        assert _spoc_status_from_expiry(None) == "active"

    def test_future_expiry_is_active(self):
        future = (datetime.now(tz=timezone.utc) + timedelta(days=365)).isoformat()
        assert _spoc_status_from_expiry(future) == "active"

    def test_past_expiry_is_expired(self):
        past = (datetime.now(tz=timezone.utc) - timedelta(days=365)).isoformat()
        assert _spoc_status_from_expiry(past) == "expired"

    def test_invalid_string_is_unknown(self):
        assert _spoc_status_from_expiry("not-a-date") == "unknown"


# ---------------------------------------------------------------------------
# run_recommend_broker_for_deal
# ---------------------------------------------------------------------------

class TestNoBrokersFound:
    @pytest.mark.asyncio
    async def test_no_brokers_returns_ok_with_warning(self):
        """No match → status OK, brokers empty, warnings not empty."""
        driver = _make_driver()  # no brokers in any query

        result = await run_recommend_broker_for_deal(
            driver, market="Mars", asset_class="Office", service_line="Leasing"
        )

        assert result["status"] == "OK"
        assert result["brokers"] == []
        assert len(result.get("warnings", [])) > 0


class TestActiveSPOCRankedFirst:
    @pytest.mark.asyncio
    async def test_active_spoc_broker_outranks_no_spoc(self):
        """
        Broker A has an active SPOC for the client; Broker B does not.
        Broker A must appear first in the ranked list.
        """
        broker_a = {
            "broker_key": "email::a@cbre.com",
            "name": "Alice Active",
            "firm": "CBRE",
            "deal_volume": 100_000_000,
            "community_id": 1,
            "market_match": 1,
        }
        broker_b = {
            "broker_key": "email::b@jll.com",
            "name": "Bob NoSpoc",
            "firm": "JLL",
            "deal_volume": 100_000_000,  # same volume → SPOC is tiebreaker
            "community_id": 1,
            "market_match": 1,
        }

        future_date = (datetime.now(tz=timezone.utc) + timedelta(days=365)).isoformat()
        spoc_map = {
            "email::a@cbre.com": [
                {
                    "client_name": "Acme Corp",
                    "service_line": "TenantRep",
                    "expiration_date": future_date,
                }
            ],
            "email::b@jll.com": [],  # no SPOC
        }

        driver = _make_driver(
            market_brokers=[broker_a, broker_b],
            spoc_map=spoc_map,
        )

        result = await run_recommend_broker_for_deal(
            driver,
            market="Atlanta",
            asset_class="Retail",
            service_line="TenantRep",
            client_name="Acme Corp",
        )

        assert result["status"] == "OK"
        assert len(result["brokers"]) == 2

        first = result["brokers"][0]
        assert first["broker"]["id"] == "email::a@cbre.com", (
            f"Broker with active SPOC should rank first; got {first['broker']['id']}"
        )
        assert first["components"]["spoc_status"] == "active"


class TestExpiredSPOCIncluded:
    @pytest.mark.asyncio
    async def test_expired_spoc_is_not_silently_dropped(self):
        """
        api-contracts §6 + Phase 4 DoD: expired SPOCs must appear in output
        with spoc_status='expired', ranked lower than broker with active SPOC.
        """
        broker_active = {
            "broker_key": "email::active@cbre.com",
            "name": "Active Broker",
            "firm": "CBRE",
            "deal_volume": 100_000_000,  # equal volume — SPOC is the tiebreaker
            "community_id": 2,
            "market_match": 1,
        }
        broker_expired = {
            "broker_key": "email::expired@jll.com",
            "name": "Expired Broker",
            "firm": "JLL",
            "deal_volume": 100_000_000,  # equal volume — SPOC is the tiebreaker
            "community_id": 2,
            "market_match": 1,
        }

        future_date = (datetime.now(tz=timezone.utc) + timedelta(days=365)).isoformat()
        past_date = (datetime.now(tz=timezone.utc) - timedelta(days=365)).isoformat()
        spoc_map = {
            "email::active@cbre.com": [
                {
                    "client_name": "BigCo",
                    "service_line": "Leasing",
                    "expiration_date": future_date,
                }
            ],
            "email::expired@jll.com": [
                {
                    "client_name": "BigCo",
                    "service_line": "Leasing",
                    "expiration_date": past_date,
                }
            ],
        }

        driver = _make_driver(
            market_brokers=[broker_active, broker_expired],
            spoc_map=spoc_map,
        )

        result = await run_recommend_broker_for_deal(
            driver,
            market="Dallas",
            asset_class="Industrial",
            service_line="Leasing",
            client_name="BigCo",
        )

        assert result["status"] == "OK"

        broker_ids = [b["broker"]["id"] for b in result["brokers"]]

        # Expired broker must NOT be silently dropped
        assert "email::expired@jll.com" in broker_ids, (
            "Expired SPOC broker must be included in results"
        )

        # Active SPOC broker must rank above expired SPOC broker
        active_pos = broker_ids.index("email::active@cbre.com")
        expired_pos = broker_ids.index("email::expired@jll.com")
        assert active_pos < expired_pos, (
            f"Active SPOC broker (pos {active_pos}) should rank above "
            f"expired SPOC broker (pos {expired_pos})"
        )

        # Check spoc_status is correctly flagged
        expired_entry = result["brokers"][expired_pos]
        assert expired_entry["components"]["spoc_status"] == "expired"


class TestOutputShape:
    @pytest.mark.asyncio
    async def test_response_has_required_fields(self):
        broker_row = {
            "broker_key": "email::shape@cbre.com",
            "name": "Shape Broker",
            "firm": "CBRE",
            "deal_volume": 50_000_000,
            "community_id": 5,
            "market_match": 1,
        }
        driver = _make_driver(market_brokers=[broker_row])

        result = await run_recommend_broker_for_deal(
            driver, market="Chicago", asset_class="Office", service_line="Leasing"
        )

        assert result["status"] == "OK"
        assert "deal_context" in result
        assert "brokers" in result
        assert "truncated" in result

        ctx = result["deal_context"]
        assert ctx["market"] == "Chicago"
        assert ctx["asset_class"] == "Office"
        assert ctx["service_line"] == "Leasing"

        if result["brokers"]:
            b = result["brokers"][0]
            assert "broker" in b
            assert "score" in b
            assert "components" in b
            assert "reasons" in b
            assert "id" in b["broker"]
            assert "name" in b["broker"]
            # Components must include SPOC status
            assert "spoc_status" in b["components"]


class TestMyBrokerKeyCommunityOverlap:
    """M-P4-7: my_broker_key community-overlap branch raises same-community broker above different-community one."""

    @pytest.mark.asyncio
    async def test_same_community_broker_outranks_different_community(self):
        """
        3 brokers, all with equal deal_volume and no SPOC.
        Broker A (community 1) and Broker B (community 1) share community with the requesting broker.
        Broker C (community 2) does not.
        Passing my_broker_key of a community-1 broker → A and B score higher than C.
        """
        broker_a = {
            "broker_key": "email::a@cbre.com",
            "name": "Alice Same",
            "firm": "CBRE",
            "deal_volume": 100_000_000,
            "community_id": 1,
            "market_match": 1,
        }
        broker_b = {
            "broker_key": "email::b@jll.com",
            "name": "Bob Same",
            "firm": "JLL",
            "deal_volume": 100_000_000,
            "community_id": 1,
            "market_match": 1,
        }
        broker_c = {
            "broker_key": "email::c@cushman.com",
            "name": "Carol Diff",
            "firm": "Cushman",
            "deal_volume": 100_000_000,
            "community_id": 2,
            "market_match": 1,
        }

        driver = _make_driver(
            market_brokers=[broker_a, broker_b, broker_c],
            my_community=1,  # requesting broker is in community 1
        )

        result = await run_recommend_broker_for_deal(
            driver,
            market="Dallas",
            asset_class="Industrial",
            service_line="TenantRep",
            my_broker_key="email::requesting@cbre.com",  # triggers community lookup
        )

        assert result["status"] == "OK"
        assert len(result["brokers"]) == 3

        broker_ids = [b["broker"]["id"] for b in result["brokers"]]
        carol_pos = broker_ids.index("email::c@cushman.com")
        alice_pos = broker_ids.index("email::a@cbre.com")
        bob_pos = broker_ids.index("email::b@jll.com")

        # Same-community brokers must rank above the different-community one
        assert alice_pos < carol_pos, (
            f"Alice (community 1) should rank above Carol (community 2); "
            f"alice_pos={alice_pos}, carol_pos={carol_pos}"
        )
        assert bob_pos < carol_pos, (
            f"Bob (community 1) should rank above Carol (community 2); "
            f"bob_pos={bob_pos}, carol_pos={carol_pos}"
        )

        # community_overlap_with_me must be True for same-community brokers
        alice_entry = result["brokers"][alice_pos]
        carol_entry = result["brokers"][carol_pos]
        assert alice_entry["components"]["community_overlap_with_me"] is True
        assert carol_entry["components"]["community_overlap_with_me"] is False


class TestKLimit:
    @pytest.mark.asyncio
    async def test_result_capped_at_k(self):
        """k=2 should return at most 2 brokers."""
        brokers = [
            {
                "broker_key": f"email::b{i}@firm.com",
                "name": f"Broker {i}",
                "firm": "Firm",
                "deal_volume": float(i * 1_000_000),
                "community_id": None,
                "market_match": 1,
            }
            for i in range(5)
        ]
        driver = _make_driver(market_brokers=brokers)

        result = await run_recommend_broker_for_deal(
            driver, market="Houston", asset_class="Multifamily", service_line="PM", k=2
        )

        assert result["status"] == "OK"
        assert len(result["brokers"]) <= 2

    @pytest.mark.asyncio
    async def test_truncated_true_when_more_than_k_candidates(self):
        brokers = [
            {
                "broker_key": f"email::trunc{i}@firm.com",
                "name": f"Broker {i}",
                "firm": "Firm",
                "deal_volume": float(i * 1_000_000),
                "community_id": None,
                "market_match": 1,
            }
            for i in range(6)
        ]
        driver = _make_driver(market_brokers=brokers)

        result = await run_recommend_broker_for_deal(
            driver, market="Miami", asset_class="Retail", service_line="Leasing", k=3
        )

        assert result["truncated"] is True
