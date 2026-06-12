"""Tests for core/schemas.py — the contract that all layers depend on."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from core.schemas import (
    Evidence,
    ExitRules,
    OptionContract,
    TradeSignal,
    make_client_order_id,
)


# ─── Evidence ────────────────────────────────────────────────────────────────


class TestEvidence:
    def test_valid(self) -> None:
        e = Evidence(
            indicator="RSI",
            value=28.5,
            interpretation="RSI 28.5 — oversold",
            weight=0.8,
            bullish=True,
        )
        assert e.weight == 0.8
        assert e.bullish is True

    def test_weight_above_1_raises(self) -> None:
        """Legacy bug: confidence_threshold=70 instead of 0.70 must be caught."""
        with pytest.raises(ValidationError, match="Weights must be 0.0–1.0"):
            Evidence(
                indicator="RSI",
                value=28.5,
                interpretation="test",
                weight=70,   # ← the legacy bug
                bullish=True,
            )

    def test_frozen(self) -> None:
        e = Evidence(indicator="x", value=1, interpretation="y", weight=0.5, bullish=True)
        with pytest.raises(ValidationError):
            e.weight = 0.9  # type: ignore[misc]


# ─── OptionContract ───────────────────────────────────────────────────────────


class TestOptionContract:
    def _make(self, ask: float = 1.50) -> OptionContract:
        return OptionContract(
            symbol="SPY",
            direction="CALL",
            strike=500.0,
            expiry=date(2025, 6, 20),
            bid_per_share=1.45,
            ask_per_share=ask,
            mark_per_share=1.475,
            open_interest=10000,
            volume=5000,
        )

    def test_per_contract_computed_correctly(self) -> None:
        c = self._make(ask=3.50)
        assert c.ask_per_contract == pytest.approx(350.0)
        assert c.bid_per_contract == pytest.approx(145.0)
        assert c.mark_per_contract == pytest.approx(147.5)

    def test_penny_option_rejected(self) -> None:
        """Hard guard: ask < $0.10 must be rejected."""
        with pytest.raises(ValidationError, match="below \\$0.10 minimum"):
            self._make(ask=0.05)

    def test_zero_ask_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._make(ask=0.0)

    def test_is_tradable(self) -> None:
        assert self._make(ask=0.10).is_tradable is True
        assert self._make(ask=1.50).is_tradable is True


# ─── ExitRules ───────────────────────────────────────────────────────────────


class TestExitRules:
    def test_first_sell_requires_channel(self) -> None:
        with pytest.raises(ValidationError, match="requires source_channel_id"):
            ExitRules(strategy="FIRST_SELL_FROM_SOURCE")

    def test_partial_sell_requires_pct(self) -> None:
        with pytest.raises(ValidationError, match="requires partial_sell_pct"):
            ExitRules(strategy="PARTIAL_SELL_PCT", source_channel_id="123")

    def test_price_target_requires_multiplier(self) -> None:
        with pytest.raises(ValidationError, match="requires price_target_multiplier"):
            ExitRules(strategy="PRICE_TARGET")

    def test_manual_no_extras_needed(self) -> None:
        rules = ExitRules(strategy="MANUAL")
        assert rules.strategy == "MANUAL"

    def test_partial_sell_70_pct(self) -> None:
        rules = ExitRules(
            strategy="PARTIAL_SELL_PCT",
            partial_sell_pct=0.70,
            source_channel_id="789456123",
        )
        assert rules.partial_sell_pct == pytest.approx(0.70)

    def test_price_target_multiplier(self) -> None:
        rules = ExitRules(strategy="PRICE_TARGET", price_target_multiplier=1.05)
        assert rules.price_target_multiplier == pytest.approx(1.05)


# ─── TradeSignal ─────────────────────────────────────────────────────────────


class TestTradeSignal:
    def _make_evidence(self, bullish: bool = True) -> Evidence:
        return Evidence(
            indicator="test",
            value=1,
            interpretation="test signal",
            weight=0.7,
            bullish=bullish,
        )

    def _make_signal(self, confidence: float = 0.75) -> TradeSignal:
        return TradeSignal(
            analyst_id="test_analyst",
            source_layer="DISCORD",
            timestamp=datetime.now(tz=timezone.utc),
            symbol="SPY",
            direction="CALL",
            strike=500.0,
            expiry=date(2025, 6, 20),
            signal_price=1.50,
            evidence=[self._make_evidence()],
            risk_level="MEDIUM",
            confidence=confidence,
            exit_rules=ExitRules(strategy="MANUAL"),
        )

    def test_valid_signal(self) -> None:
        s = self._make_signal()
        assert s.analyst_id == "test_analyst"
        assert s.symbol == "SPY"
        assert s.status == "PENDING"

    def test_symbol_uppercased(self) -> None:
        s = TradeSignal(
            analyst_id="x",
            source_layer="DISCORD",
            timestamp=datetime.now(tz=timezone.utc),
            symbol="spy",  # lowercase
            direction="CALL",
            strike=500.0,
            expiry=date(2025, 6, 20),
            signal_price=1.50,
            evidence=[self._make_evidence()],
            risk_level="LOW",
            confidence=0.80,
            exit_rules=ExitRules(strategy="MANUAL"),
        )
        assert s.symbol == "SPY"

    def test_confidence_above_1_raises(self) -> None:
        """Legacy bug: confidence=75 instead of 0.75 must be caught."""
        with pytest.raises(ValidationError, match="Must be a fraction"):
            self._make_signal(confidence=75)

    def test_bullish_score(self) -> None:
        s = TradeSignal(
            analyst_id="x",
            source_layer="DISCORD",
            timestamp=datetime.now(tz=timezone.utc),
            symbol="SPY",
            direction="CALL",
            strike=500.0,
            expiry=date(2025, 6, 20),
            signal_price=1.50,
            evidence=[
                self._make_evidence(bullish=True),
                self._make_evidence(bullish=False),
            ],
            risk_level="MEDIUM",
            confidence=0.60,
            exit_rules=ExitRules(strategy="MANUAL"),
        )
        assert s.bullish_score() == pytest.approx(0.50)

    def test_minimum_one_evidence_item(self) -> None:
        with pytest.raises(ValidationError):
            TradeSignal(
                analyst_id="x",
                source_layer="DISCORD",
                timestamp=datetime.now(tz=timezone.utc),
                symbol="SPY",
                direction="CALL",
                strike=500.0,
                expiry=date(2025, 6, 20),
                signal_price=1.50,
                evidence=[],  # empty
                risk_level="LOW",
                confidence=0.80,
                exit_rules=ExitRules(strategy="MANUAL"),
            )

    def test_frozen(self) -> None:
        s = self._make_signal()
        with pytest.raises(ValidationError):
            s.symbol = "AAPL"  # type: ignore[misc]


# ─── make_client_order_id ────────────────────────────────────────────────────


class TestClientOrderId:
    def test_deterministic(self) -> None:
        kwargs = dict(
            analyst_id="vinod_spx",
            action="BUY",
            symbol="SPX",
            direction="CALL",
            strike=5800.0,
            expiry=date(2025, 6, 20),
            qty=1,
            trade_date=date(2025, 6, 12),
        )
        id1 = make_client_order_id(**kwargs)  # type: ignore[arg-type]
        id2 = make_client_order_id(**kwargs)  # type: ignore[arg-type]
        assert id1 == id2

    def test_different_inputs_different_ids(self) -> None:
        base = dict(
            analyst_id="vinod_spx",
            action="BUY",
            symbol="SPX",
            direction="CALL",
            strike=5800.0,
            expiry=date(2025, 6, 20),
            qty=1,
            trade_date=date(2025, 6, 12),
        )
        id1 = make_client_order_id(**base)  # type: ignore[arg-type]
        id2 = make_client_order_id(**{**base, "strike": 5900.0})  # type: ignore[arg-type]
        assert id1 != id2

    def test_length_32_chars(self) -> None:
        oid = make_client_order_id(
            analyst_id="test",
            action="BUY",
            symbol="SPY",
            direction="PUT",
            strike=500.0,
            expiry=date(2025, 6, 20),
            qty=2,
            trade_date=date(2025, 6, 12),
        )
        assert len(oid) == 32
