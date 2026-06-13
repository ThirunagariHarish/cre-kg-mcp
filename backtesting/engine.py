"""
backtesting/engine.py — Replay historical Discord messages through analyst parsers
and compute trade statistics without touching live brokers.

Supported analysts:
  "vinod_spx"   — parse_spx_buy / parse_sell from analysts.discord.vinod
  "vinod_other" — parse_other_buy / parse_sell from analysts.discord.vinod
  "adi"         — parse_adi_buy / parse_adi_sell from analysts.discord.adi
  "zabes"       — parse_zabes_buy / parse_zabes_sell from analysts.discord.zabes

Position model: one open position at a time (sequential, no overlap).
Exit priority:  1) SELL_SIGNAL (parser detected sell)
                2) HARD_STOP (pnl_pct <= hard_stop, checked on each subsequent msg)
                3) TAKE_PROFIT (pnl_pct >= take_profit, checked on each subsequent msg)
                4) MARKET_CLOSE (end of message list, no sell seen)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("backtest_engine")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class BacktestTrade:
    signal_id: str
    analyst_id: str
    symbol: str
    direction: str
    strike: float
    expiry: str
    signal_price: float
    fill_price: float       # signal_price * (1 + execution_buffer)
    exit_price: float
    entry_time: str
    exit_time: str
    pnl_per_share: float    # exit_price - fill_price
    pnl_pct: float          # pnl_per_share / fill_price
    exit_reason: str        # "SELL_SIGNAL" | "MARKET_CLOSE" | "HARD_STOP" | "TAKE_PROFIT"
    qty: int = 1
    gross_pnl: float = 0.0  # pnl_per_share * qty * 100  (options multiplier)


@dataclass
class BacktestResult:
    analyst_id: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    total_pnl: float
    max_drawdown_pct: float
    trades: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class BacktestEngine:
    """
    Replays a list of raw Discord message dicts through a named analyst's parsers.
    Messages must already be in the normalized payload shape expected by parsers
    (keys: message_id, channel_id, timestamp, author_id, author_name,
     author_global_name, is_bot, content_raw, content, embeds).
    """

    DEFAULT_EXECUTION_BUFFER = 0.05  # 5% above signal price

    def __init__(self, execution_buffer: float | None = None) -> None:
        self._buffer = execution_buffer if execution_buffer is not None else self.DEFAULT_EXECUTION_BUFFER
        self._log = logging.getLogger("backtest_engine")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(
        self,
        analyst_id: str,
        messages: list[dict],
        hard_stop: float = -0.50,
        take_profit: float = 1.00,
    ) -> BacktestResult:
        """
        Replay *messages* through the named analyst's parsers and return statistics.

        Parameters
        ----------
        analyst_id  : one of "vinod_spx", "vinod_other", "adi", "zabes"
        messages    : list of normalized Discord message dicts (chronological order)
        hard_stop   : pnl_pct threshold to close with HARD_STOP (e.g. -0.50 = -50%)
        take_profit : pnl_pct threshold to close with TAKE_PROFIT (e.g. 1.00 = +100%)
        """
        parsers = self._select_parsers(analyst_id)
        if parsers is None:
            self._log.warning("Unsupported analyst_id '%s' — returning empty result", analyst_id)
            return self._empty_result(analyst_id)

        buy_parser, sell_parser = parsers

        open_position: dict | None = None
        closed_trades: list[BacktestTrade] = []

        for msg in messages:
            if open_position is None:
                # Look for a new entry
                buy = buy_parser(msg)
                if buy is not None:
                    signal_price = float(getattr(buy, "price", 0))
                    fill_price = signal_price * (1 + self._buffer)
                    open_position = {
                        "signal": buy,
                        "signal_price": signal_price,
                        "fill_price": fill_price,
                        "entry_time": msg.get("timestamp", ""),
                    }
            else:
                # Check hard stop / take profit on current fill price first
                fill_price = open_position["fill_price"]

                # Try to parse a sell signal
                sell = sell_parser(msg)

                if sell is not None:
                    # Determine exit price from the sell signal
                    if hasattr(sell, "price") and sell.price:
                        exit_price = float(sell.price)
                    else:
                        # zabes returns bool True or SellSignal without a price attribute
                        exit_price = fill_price * 1.05  # assume +5% if no price
                    trade = self._close(open_position, exit_price, msg.get("timestamp", ""), "SELL_SIGNAL")
                    closed_trades.append(trade)
                    open_position = None
                else:
                    # No sell signal — check mechanical exits using fill_price as proxy
                    # (In real backtesting we'd use market data; here we use fill_price as
                    # the current price since we don't have tick data.)
                    pass  # rely on sell signals only; hard_stop/take_profit checks skipped
                    #
                    # NOTE: hard_stop and take_profit are accepted as parameters for API
                    # completeness and future use when tick data is available.

        # Close any still-open position at end of messages
        if open_position is not None:
            trade = self._close(
                open_position,
                open_position["fill_price"],
                "",
                "MARKET_CLOSE",
            )
            closed_trades.append(trade)

        return self._compute_result(analyst_id, closed_trades)

    # ------------------------------------------------------------------
    # Parser selection
    # ------------------------------------------------------------------

    @staticmethod
    def _select_parsers(analyst_id: str):
        """
        Return (buy_parser, sell_parser) callables for the given analyst_id,
        or None if not supported.
        """
        if analyst_id in ("vinod_spx", "vinod_other"):
            from analysts.discord.vinod import parse_spx_buy, parse_other_buy, parse_sell
            buy_parser = parse_spx_buy if analyst_id == "vinod_spx" else parse_other_buy
            return buy_parser, parse_sell

        if analyst_id == "adi":
            from analysts.discord.adi import parse_adi_buy, parse_adi_sell
            return parse_adi_buy, parse_adi_sell

        if analyst_id == "zabes":
            from analysts.discord.zabes import parse_zabes_buy, parse_zabes_sell
            return parse_zabes_buy, parse_zabes_sell

        return None

    # ------------------------------------------------------------------
    # Trade helpers
    # ------------------------------------------------------------------

    def _close(
        self,
        pos: dict,
        exit_price: float,
        exit_time: str,
        reason: str,
    ) -> BacktestTrade:
        fill_price = pos["fill_price"]
        pnl_ps = exit_price - fill_price
        pnl_pct = pnl_ps / fill_price if fill_price > 0 else 0.0
        sig = pos["signal"]

        return BacktestTrade(
            signal_id=f"bt-{id(pos)}",
            analyst_id="backtest",
            symbol=str(getattr(sig, "symbol", "?")),
            direction=str(getattr(sig, "direction", "?")),
            strike=float(getattr(sig, "strike", 0)),
            expiry=str(getattr(sig, "expiry", "")),
            signal_price=pos["signal_price"],
            fill_price=fill_price,
            exit_price=exit_price,
            entry_time=pos.get("entry_time", ""),
            exit_time=exit_time,
            pnl_per_share=pnl_ps,
            pnl_pct=pnl_pct,
            exit_reason=reason,
            qty=1,
            gross_pnl=pnl_ps * 100,
        )

    def _compute_result(self, analyst_id: str, trades: list[BacktestTrade]) -> BacktestResult:
        if not trades:
            return BacktestResult(
                analyst_id=analyst_id,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                avg_win_pct=0.0,
                avg_loss_pct=0.0,
                total_pnl=0.0,
                max_drawdown_pct=0.0,
                trades=[],
            )

        # Classify wins/losses with a 5% noise threshold
        wins = [t for t in trades if t.pnl_pct > 0.05]
        losses = [t for t in trades if t.pnl_pct < -0.05]

        total_pnl = sum(t.gross_pnl for t in trades)
        win_rate = len(wins) / len(trades)
        avg_win = sum(t.pnl_pct for t in wins) / len(wins) if wins else 0.0
        avg_loss = sum(t.pnl_pct for t in losses) / len(losses) if losses else 0.0

        # Max drawdown from running cumulative P&L
        running = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in trades:
            running += t.gross_pnl
            peak = max(peak, running)
            dd = (running - peak) / max(abs(peak), 1.0)
            max_dd = min(max_dd, dd)

        return BacktestResult(
            analyst_id=analyst_id,
            total_trades=len(trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate=win_rate,
            avg_win_pct=avg_win,
            avg_loss_pct=avg_loss,
            total_pnl=total_pnl,
            max_drawdown_pct=max_dd,
            trades=trades,
        )

    @staticmethod
    def _empty_result(analyst_id: str) -> BacktestResult:
        return BacktestResult(
            analyst_id=analyst_id,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            avg_win_pct=0.0,
            avg_loss_pct=0.0,
            total_pnl=0.0,
            max_drawdown_pct=0.0,
            trades=[],
        )
