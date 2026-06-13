"""
tests/unit/test_backtest_engine.py — Unit tests for BacktestEngine.

Run:
    cd <worktree_root> && python -m pytest tests/unit/test_backtest_engine.py -v
"""

from __future__ import annotations

import asyncio

import pytest

from backtesting.engine import BacktestEngine, BacktestResult


# ---------------------------------------------------------------------------
# Message factories
# ---------------------------------------------------------------------------

def _make_vinod_buy_msg(content: str) -> dict:
    """Simulate an INFRA TRADE ALERT bot buy message (Vinod SPX channel)."""
    return {
        "message_id": "1",
        "channel_id": "1495516216645783562",
        "timestamp": "2026-06-12T14:00:00+00:00",
        "author_id": "9001",
        "author_name": "INFRA TRADE ALERT",
        "author_global_name": "INFRA TRADE ALERT",
        "is_bot": True,
        "content_raw": content,
        "content": content,
        "embeds": [],
    }


def _make_vinod_sell_msg(content: str) -> dict:
    """Simulate a singhvinod77 bot sell message."""
    return {
        "message_id": "2",
        "channel_id": "1495516216645783562",
        "timestamp": "2026-06-12T15:00:00+00:00",
        "author_id": "9002",
        "author_name": "singhvinod77",
        "author_global_name": "singhvinod77",
        "is_bot": True,
        "content_raw": content,
        "content": content,
        "embeds": [],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    """Run a coroutine synchronously."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBacktestEngine:
    def setup_method(self):
        self.engine = BacktestEngine()

    # ── happy path ─────────────────────────────────────────────────────────

    def test_buy_then_sell_produces_trade(self):
        """A matched buy→sell pair should produce exactly one closed trade with positive P&L."""
        msgs = [
            _make_vinod_buy_msg("**SPX :** Bought SPX 7550C at 3.50"),
            _make_vinod_sell_msg("@here Sold 50% SPX 7550C at 7.00"),
        ]
        result = run(self.engine.run("vinod_spx", msgs))

        assert result.total_trades == 1
        trade = result.trades[0]
        assert trade.pnl_per_share > 0, "Exit at 7.00 > fill at 3.50*1.05 should be profitable"
        assert trade.exit_reason == "SELL_SIGNAL"
        assert trade.symbol == "SPX"
        assert trade.direction == "CALL"

    def test_buy_without_sell_closes_at_market_close(self):
        """An open position with no sell message should close as MARKET_CLOSE at fill price."""
        msgs = [
            _make_vinod_buy_msg("**SPX :** Bought SPX 5300C at 2.00"),
        ]
        result = run(self.engine.run("vinod_spx", msgs))

        assert result.total_trades == 1
        trade = result.trades[0]
        assert trade.exit_reason == "MARKET_CLOSE"
        # Exit at fill_price → P&L = 0
        assert abs(trade.pnl_per_share) < 1e-9

    # ── edge cases ─────────────────────────────────────────────────────────

    def test_empty_messages(self):
        """Empty message list should produce a zero-trade result."""
        result = run(self.engine.run("vinod_spx", []))

        assert result.total_trades == 0
        assert result.win_rate == 0.0
        assert result.total_pnl == 0.0
        assert result.trades == []

    def test_unsupported_analyst(self):
        """Unknown analyst_id should return an empty BacktestResult immediately."""
        msgs = [_make_vinod_buy_msg("**SPX :** Bought SPX 5300C at 2.00")]
        result = run(self.engine.run("unknown_analyst", msgs))

        assert isinstance(result, BacktestResult)
        assert result.total_trades == 0

    def test_sell_without_prior_buy_is_ignored(self):
        """A sell message with no open position must not create a trade."""
        msgs = [
            _make_vinod_sell_msg("@here Sold 50% SPX 5300C at 5.00"),
        ]
        result = run(self.engine.run("vinod_spx", msgs))

        assert result.total_trades == 0

    # ── statistics ─────────────────────────────────────────────────────────

    def test_win_rate_3_wins_2_losses(self):
        """
        Construct 5 trade pairs — 3 profitable (exit > fill), 2 losing (exit < fill) —
        and verify that win_rate rounds to ~0.60.

        Signal prices and exits are chosen to clear the ±5% noise band used by
        _compute_result (wins: pnl_pct > 0.05, losses: pnl_pct < -0.05).
        """
        # fill_price = signal_price * 1.05 (DEFAULT_EXECUTION_BUFFER)
        # For a *win*  we need exit > fill * 1.05  → exit > signal * 1.1025
        # For a *loss* we need exit < fill * 0.95  → exit < signal * 0.9975
        #
        # Winning pairs: sell at 2× signal (100% gain, well above +5%)
        # Losing pairs:  sell at 0.40× signal (−60% loss, well below -5%)
        winning_pairs = [
            ("**SPX :** Bought SPX 5000C at 1.00", "@here Sold 50% SPX 5000C at 2.00"),
            ("**SPX :** Bought SPX 5100C at 2.00", "@here Sold 50% SPX 5100C at 4.00"),
            ("**SPX :** Bought SPX 5200C at 3.00", "@here Sold 50% SPX 5200C at 6.00"),
        ]
        losing_pairs = [
            ("**SPX :** Bought SPX 5300P at 4.00", "@here Sold 50% SPX 5300P at 1.60"),
            ("**SPX :** Bought SPX 5400P at 5.00", "@here Sold 50% SPX 5400P at 2.00"),
        ]

        msgs: list[dict] = []
        ts_idx = 0

        def buy_msg(content: str) -> dict:
            nonlocal ts_idx
            ts_idx += 1
            m = _make_vinod_buy_msg(content)
            m["message_id"] = f"buy-{ts_idx}"
            m["timestamp"] = f"2026-06-12T{ts_idx:02d}:00:00+00:00"
            return m

        def sell_msg(content: str) -> dict:
            nonlocal ts_idx
            ts_idx += 1
            m = _make_vinod_sell_msg(content)
            m["message_id"] = f"sell-{ts_idx}"
            m["timestamp"] = f"2026-06-12T{ts_idx:02d}:30:00+00:00"
            return m

        for buy_c, sell_c in winning_pairs + losing_pairs:
            msgs.append(buy_msg(buy_c))
            msgs.append(sell_msg(sell_c))

        result = run(self.engine.run("vinod_spx", msgs))

        assert result.total_trades == 5
        assert result.winning_trades == 3
        assert result.losing_trades == 2
        assert abs(result.win_rate - 0.60) < 0.01, f"Expected ~0.60 got {result.win_rate}"

    def test_gross_pnl_uses_options_multiplier(self):
        """gross_pnl = pnl_per_share * qty * 100 (options multiplier)."""
        msgs = [
            _make_vinod_buy_msg("**SPX :** Bought SPX 5500C at 2.00"),
            _make_vinod_sell_msg("@here Sold 50% SPX 5500C at 4.00"),
        ]
        result = run(self.engine.run("vinod_spx", msgs))

        assert result.total_trades == 1
        trade = result.trades[0]
        expected_gross = trade.pnl_per_share * trade.qty * 100
        assert abs(trade.gross_pnl - expected_gross) < 1e-6

    def test_total_pnl_equals_sum_of_gross_pnl(self):
        """BacktestResult.total_pnl must equal sum of all trade gross_pnl values."""
        msgs = [
            _make_vinod_buy_msg("**SPX :** Bought SPX 5000C at 1.00"),
            _make_vinod_sell_msg("@here Sold 50% SPX 5000C at 2.00"),
            _make_vinod_buy_msg("**SPX :** Bought SPX 5100P at 2.00"),
            _make_vinod_sell_msg("@here Sold 50% SPX 5100P at 1.00"),
        ]
        # Need unique timestamps so sort order is predictable
        msgs[0]["timestamp"] = "2026-06-12T10:00:00+00:00"
        msgs[1]["timestamp"] = "2026-06-12T11:00:00+00:00"
        msgs[2]["timestamp"] = "2026-06-12T12:00:00+00:00"
        msgs[3]["timestamp"] = "2026-06-12T13:00:00+00:00"

        result = run(self.engine.run("vinod_spx", msgs))

        assert result.total_trades == 2
        assert abs(result.total_pnl - sum(t.gross_pnl for t in result.trades)) < 1e-6

    # ── analyst routing ────────────────────────────────────────────────────

    def test_adi_analyst_routing(self):
        """Engine correctly routes 'adi' to parse_adi_buy / parse_adi_sell."""
        buy_msg = {
            "message_id": "a1",
            "channel_id": "1495517143599415507",
            "timestamp": "2026-06-12T14:00:00+00:00",
            "author_id": "888",
            "author_name": "Aadi [INFR]",
            "author_global_name": "Aadi [INFR]",
            "is_bot": True,
            "content_raw": "@here SPX 5300C at 2.50",
            "content": "@here SPX 5300C at 2.50",
            "embeds": [],
        }
        sell_msg = {
            "message_id": "a2",
            "channel_id": "1495517143599415507",
            "timestamp": "2026-06-12T15:00:00+00:00",
            "author_id": "888",
            "author_name": "Aadi [INFR]",
            "author_global_name": "Aadi [INFR]",
            "is_bot": True,
            "content_raw": "@here Sold SPX 5300C at 5.00",
            "content": "@here Sold SPX 5300C at 5.00",
            "embeds": [],
        }
        result = run(self.engine.run("adi", [buy_msg, sell_msg]))

        assert result.total_trades == 1
        assert result.trades[0].pnl_per_share > 0

    def test_zabes_analyst_routing(self):
        """Engine correctly routes 'zabes' to parse_zabes_buy / parse_zabes_sell."""
        buy_msg = {
            "message_id": "z1",
            "channel_id": "1495516822349414430",
            "timestamp": "2026-06-12T14:00:00+00:00",
            "author_id": "777",
            "author_name": "Waxui",
            "author_global_name": "Waxui",
            "is_bot": False,
            "content_raw": "@here SPY here\n06/20 735P\nAvg. 1.50",
            "content": "@here SPY here\n06/20 735P\nAvg. 1.50",
            "embeds": [],
        }
        sell_msg = {
            "message_id": "z2",
            "channel_id": "1495516822349414430",
            "timestamp": "2026-06-12T15:00:00+00:00",
            "author_id": "777",
            "author_name": "Waxui",
            "author_global_name": "Waxui",
            "is_bot": False,
            "content_raw": "Sold all — out of SPY puts",
            "content": "Sold all — out of SPY puts",
            "embeds": [],
        }
        result = run(self.engine.run("zabes", [buy_msg, sell_msg]))

        assert result.total_trades == 1
        assert result.trades[0].exit_reason == "SELL_SIGNAL"
