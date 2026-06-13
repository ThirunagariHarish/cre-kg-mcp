"""
tests/integration/test_multi_account_gateway.py

Integration tests for MultiAccountGateway and AccountManager.

All tests run without real Robinhood credentials or Redis.
AccountGateway instances are replaced with mocks where the test
focus is on the fan-out logic of MultiAccountGateway.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.schemas import Evidence, ExitRules, OrderRecord, PositionRecord, TradeSignal
from gateway.account_manager import AccountConfig, load_accounts
from gateway.multi_account_gateway import AccountGateway, MultiAccountGateway


# ─────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────

def _make_signal(
    symbol: str = "SPY",
    direction: str = "CALL",
    strike: float = 500.0,
    expiry: date | None = None,
    signal_price: float = 1.50,
    analyst_id: str = "test_analyst",
) -> TradeSignal:
    if expiry is None:
        expiry = date.today() + timedelta(days=7)
    return TradeSignal(
        analyst_id=analyst_id,
        source_layer="DISCORD",
        timestamp=datetime.now(tz=timezone.utc),
        symbol=symbol,
        direction=direction,  # type: ignore[arg-type]
        strike=strike,
        expiry=expiry,
        signal_price=signal_price,
        evidence=[
            Evidence(
                indicator="EMA",
                value="above 200",
                interpretation="Bullish trend",
                weight=0.8,
                bullish=True,
            )
        ],
        risk_level="MEDIUM",
        confidence=0.75,
        exit_rules=ExitRules(strategy="MANUAL"),
    )


def _make_position(
    symbol: str = "SPY",
    direction: str = "CALL",
    strike: float = 500.0,
    expiry: date | None = None,
    qty: int = 1,
    avg_cost: float = 1.50,
    analyst_id: str = "test_analyst",
    signal_id: str = "test-signal-id",
    order_id: str = "test-order-id",
) -> PositionRecord:
    if expiry is None:
        expiry = date.today() + timedelta(days=7)
    return PositionRecord(
        order_id=order_id,
        signal_id=signal_id,
        analyst_id=analyst_id,
        symbol=symbol,
        direction=direction,  # type: ignore[arg-type]
        strike=strike,
        expiry=expiry,
        qty=qty,
        avg_cost_per_share=avg_cost,
        avg_cost_per_contract=avg_cost * 100,
        opened_at=datetime.now(tz=timezone.utc),
        exit_rules=ExitRules(strategy="MANUAL"),
    )


def _make_order_record(account_id: str = "primary") -> OrderRecord:
    expiry = date.today() + timedelta(days=7)
    return OrderRecord(
        order_id=f"order-{account_id}",
        client_order_id=f"client-{account_id}",
        signal_id="test-signal-id",
        analyst_id="test_analyst",
        symbol="SPY",
        direction="CALL",  # type: ignore[arg-type]
        strike=500.0,
        expiry=expiry,
        qty=1,
        limit_price_per_share=1.50,
        limit_price_per_contract=150.0,
        submitted_at=datetime.now(tz=timezone.utc),
        status="FILLED",
        paper_mode=True,
    )


def _make_account_config(
    account_id: str = "primary",
    enabled: bool = True,
    paper_mode: bool = True,
    max_position_size_usd: float = 200.0,
) -> AccountConfig:
    return AccountConfig(
        account_id=account_id,
        display_name=f"{account_id.title()} Account",
        username_secret=f"RH_USER_{account_id.upper()}",
        password_secret=f"RH_PASS_{account_id.upper()}",
        totp_secret=f"RH_TOTP_{account_id.upper()}",
        paper_mode=paper_mode,
        enabled=enabled,
        max_position_size_usd=max_position_size_usd,
        notes=f"Test {account_id} account",
    )


def _mock_account_gateway(account_id: str, order: OrderRecord | None = None) -> MagicMock:
    """Return a MagicMock shaped like AccountGateway."""
    gw = MagicMock(spec=AccountGateway)
    gw.account_id = account_id
    gw.display_name = f"{account_id.title()} Account"
    gw.paper_mode = True
    gw.execute_signal = AsyncMock(return_value=order or _make_order_record(account_id))
    gw.close_position = AsyncMock(return_value=_make_order_record(account_id))
    gw.get_positions = AsyncMock(return_value=[])
    gw.get_account = AsyncMock(return_value={"account_id": account_id, "paper_mode": True})
    return gw


# ─────────────────────────────────────────────
# Tests — fan-out execution
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_multi_account_executes_in_all():
    """execute_signal fans out to every AccountGateway and collects results."""
    gw_primary = _mock_account_gateway("primary")
    gw_secondary = _mock_account_gateway("secondary")

    mag = MultiAccountGateway.__new__(MultiAccountGateway)
    mag._gateways = [gw_primary, gw_secondary]
    mag._redis = None

    signal = _make_signal()
    results = await mag.execute_signal(signal)

    gw_primary.execute_signal.assert_awaited_once_with(signal)
    gw_secondary.execute_signal.assert_awaited_once_with(signal)

    assert "primary" in results
    assert "secondary" in results
    assert results["primary"] is not None
    assert results["secondary"] is not None


@pytest.mark.asyncio
async def test_one_account_failure_doesnt_block():
    """If one account raises, the other still executes and result is None for the failed one."""
    gw_primary = _mock_account_gateway("primary")
    gw_primary.execute_signal = AsyncMock(side_effect=RuntimeError("RH connection error"))

    gw_secondary = _mock_account_gateway("secondary")
    secondary_order = _make_order_record("secondary")
    gw_secondary.execute_signal = AsyncMock(return_value=secondary_order)

    mag = MultiAccountGateway.__new__(MultiAccountGateway)
    mag._gateways = [gw_primary, gw_secondary]
    mag._redis = None

    signal = _make_signal()
    results = await mag.execute_signal(signal)

    # Primary failed — should be None, not raise
    assert results["primary"] is None
    # Secondary still executed and returned its order
    assert results["secondary"] is secondary_order
    gw_secondary.execute_signal.assert_awaited_once_with(signal)


# ─────────────────────────────────────────────
# Tests — load_accounts
# ─────────────────────────────────────────────

def test_load_accounts_respects_enabled():
    """Disabled accounts must not appear in the returned list."""
    config = {
        "accounts": [
            {
                "account_id": "primary",
                "display_name": "Primary",
                "username_secret": "RH_USER",
                "password_secret": "RH_PASS",
                "totp_secret": "RH_TOTP",
                "paper_mode": True,
                "enabled": True,
                "max_position_size_usd": 200,
                "notes": "",
            },
            {
                "account_id": "secondary",
                "display_name": "Secondary",
                "username_secret": "RH_USER_2",
                "password_secret": "RH_PASS_2",
                "totp_secret": "RH_TOTP_2",
                "paper_mode": True,
                "enabled": False,
                "max_position_size_usd": 100,
                "notes": "disabled",
            },
        ],
        "global_paper_mode_override": False,
        "execute_in_all_accounts": True,
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
        json.dump(config, fh)
        tmp_path = fh.name

    try:
        accounts = load_accounts(tmp_path)
    finally:
        os.unlink(tmp_path)

    assert len(accounts) == 1
    assert accounts[0].account_id == "primary"


def test_global_paper_override():
    """global_paper_mode_override=true must force paper_mode=True on all accounts."""
    config = {
        "accounts": [
            {
                "account_id": "live_account",
                "display_name": "Live",
                "username_secret": "RH_USER",
                "password_secret": "RH_PASS",
                "totp_secret": "RH_TOTP",
                "paper_mode": False,  # would be live...
                "enabled": True,
                "max_position_size_usd": 500,
                "notes": "should be forced to paper",
            },
        ],
        "global_paper_mode_override": True,  # ...but override forces paper
        "execute_in_all_accounts": True,
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
        json.dump(config, fh)
        tmp_path = fh.name

    try:
        accounts = load_accounts(tmp_path)
    finally:
        os.unlink(tmp_path)

    assert len(accounts) == 1
    assert accounts[0].paper_mode is True, "global_paper_mode_override should force paper_mode"


# ─────────────────────────────────────────────
# Tests — close_position_all
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_close_all_accounts():
    """close_position_all fans the close call to every AccountGateway."""
    gw_primary = _mock_account_gateway("primary")
    gw_secondary = _mock_account_gateway("secondary")

    mag = MultiAccountGateway.__new__(MultiAccountGateway)
    mag._gateways = [gw_primary, gw_secondary]
    mag._redis = None

    position = _make_position()
    results = await mag.close_position_all(position, qty=1, reason="TEST_CLOSE")

    gw_primary.close_position.assert_awaited_once_with(position, 1, "TEST_CLOSE")
    gw_secondary.close_position.assert_awaited_once_with(position, 1, "TEST_CLOSE")

    assert "primary" in results
    assert "secondary" in results
    assert results["primary"] is not None
    assert results["secondary"] is not None
