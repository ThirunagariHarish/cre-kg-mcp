"""
tests/unit/test_polygon_client.py — Unit tests for core/polygon_client.py
"""

from __future__ import annotations

import time
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.polygon_client import PolygonClient
from core.schemas import OptionContract


# ─────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────

def _make_client(api_key: str = "test-key") -> PolygonClient:
    client = PolygonClient(api_key=api_key)
    return client


def _make_contract(bid: float = 1.0, ask: float = 1.4) -> OptionContract:
    return OptionContract(
        symbol="SPY",
        direction="CALL",
        strike=450.0,
        expiry=date(2025, 12, 19),
        bid_per_share=bid,
        ask_per_share=ask,
        mark_per_share=(bid + ask) / 2,
        open_interest=500,
        volume=1000,
    )


# ─────────────────────────────────────────────────────────
# test_ticker_format
# ─────────────────────────────────────────────────────────

def test_ticker_format_call() -> None:
    client = _make_client()
    ticker = client._build_ticker("SPY", "CALL", 450.0, date(2025, 12, 19))
    assert ticker == "O:SPY251219C00450000"


def test_ticker_format_put() -> None:
    client = _make_client()
    ticker = client._build_ticker("AAPL", "PUT", 200.0, date(2024, 6, 21))
    assert ticker == "O:AAPL240621P00200000"


def test_ticker_format_fractional_strike() -> None:
    """Strike with cents should encode correctly (e.g. 450.50 -> 00450500)."""
    client = _make_client()
    ticker = client._build_ticker("QQQ", "CALL", 450.5, date(2025, 1, 17))
    assert ticker == "O:QQQ250117C00450500"


# ─────────────────────────────────────────────────────────
# test_cache_hit
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cache_hit() -> None:
    """Second call within TTL must not make an HTTP request."""
    client = _make_client()
    contract = _make_contract()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": {
            "details": {},
            "day": {"volume": 1000, "open": 1.0, "close": 1.4},
            "greeks": {},
            "last_quote": {"bid": 1.0, "ask": 1.4},
            "open_interest": 500,
            "implied_volatility": 0.25,
        }
    }

    with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_response) as mock_get:
        # First call — should hit HTTP
        result1 = await client.get_option_quote("SPY", "CALL", 450.0, date(2025, 12, 19))
        assert mock_get.call_count == 1

        # Second call immediately — should use cache
        result2 = await client.get_option_quote("SPY", "CALL", 450.0, date(2025, 12, 19))
        assert mock_get.call_count == 1  # no additional HTTP call

        assert result1 is result2  # exact same cached object

    await client.close()


@pytest.mark.asyncio
async def test_cache_expires_after_ttl() -> None:
    """After TTL expires the client should make a new HTTP request."""
    client = _make_client()
    client.CACHE_TTL = 0  # force immediate expiry

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": {
            "details": {},
            "day": {"volume": 100, "open": 1.0, "close": 1.2},
            "greeks": {},
            "last_quote": {"bid": 1.0, "ask": 1.2},
            "open_interest": 100,
        }
    }

    with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_response) as mock_get:
        await client.get_option_quote("SPY", "CALL", 450.0, date(2025, 12, 19))
        await client.get_option_quote("SPY", "CALL", 450.0, date(2025, 12, 19))
        assert mock_get.call_count == 2

    await client.close()


# ─────────────────────────────────────────────────────────
# test_no_api_key_uses_yfinance
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_api_key_uses_yfinance(monkeypatch: pytest.MonkeyPatch) -> None:
    """When POLYGON_API_KEY is not set the client calls _yfinance_fallback."""
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)

    client = PolygonClient(api_key="")  # explicitly empty
    assert not client._enabled

    expected_contract = _make_contract()
    with patch.object(
        client,
        "_yfinance_fallback",
        new_callable=AsyncMock,
        return_value=expected_contract,
    ) as mock_fallback:
        result = await client.get_option_quote("SPY", "CALL", 450.0, date(2025, 12, 19))
        mock_fallback.assert_called_once_with("SPY", "CALL", 450.0, date(2025, 12, 19))
        assert result is expected_contract

    await client.close()


# ─────────────────────────────────────────────────────────
# test_spread_calculation
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_spread_calculation() -> None:
    """bid=1.0, ask=1.4 -> spread_pct = (1.4-1.0)/((1.4+1.0)/2) = 0.4/1.2 ≈ 0.333"""
    client = _make_client()
    contract = _make_contract(bid=1.0, ask=1.4)

    with patch.object(
        client,
        "get_option_quote",
        new_callable=AsyncMock,
        return_value=contract,
    ):
        spread = await client.get_bid_ask_spread_pct("SPY", "CALL", 450.0, date(2025, 12, 19))

    assert spread is not None
    assert abs(spread - (0.4 / 1.2)) < 1e-6


@pytest.mark.asyncio
async def test_spread_returns_none_when_no_quote() -> None:
    client = _make_client()
    with patch.object(
        client,
        "get_option_quote",
        new_callable=AsyncMock,
        return_value=None,
    ):
        spread = await client.get_bid_ask_spread_pct("SPY", "CALL", 450.0, date(2025, 12, 19))
    assert spread is None

    await client.close()


# ─────────────────────────────────────────────────────────
# test_polygon_non_200_falls_back
# ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_polygon_non_200_falls_back() -> None:
    """Non-200 Polygon response should trigger yfinance fallback."""
    client = _make_client()
    expected = _make_contract()

    mock_response = MagicMock()
    mock_response.status_code = 429  # rate limited

    with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_response):
        with patch.object(
            client,
            "_yfinance_fallback",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_fallback:
            result = await client.get_option_quote("SPY", "CALL", 450.0, date(2025, 12, 19))
            mock_fallback.assert_called_once()
            assert result is expected

    await client.close()
