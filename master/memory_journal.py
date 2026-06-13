"""
master/memory_journal.py — SQLite-backed trade memory for RL and win-rate tracking.

DB PATH: shared/state/memory.db (created on first use via initialize()).
All DB access is async via aiosqlite.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, date
from typing import Optional

import aiosqlite

from core.schemas import PositionRecord, TradeSignal


# ─────────────────────────────────────────────
# Outcome thresholds
# ─────────────────────────────────────────────

_WIN_THRESHOLD = 0.05    # > 5% gain
_LOSS_THRESHOLD = -0.05  # < -5% loss

# RL auto-reject gate
_REJECT_WIN_RATE = 0.40
_REJECT_MIN_TRADES = 10


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _compute_outcome(pnl_pct: float) -> str:
    if pnl_pct > _WIN_THRESHOLD:
        return "WIN"
    if pnl_pct < _LOSS_THRESHOLD:
        return "LOSS"
    return "BREAKEVEN"


def _compute_pattern_type(signal: TradeSignal) -> str:
    """
    Derives a pattern label like "SPX_CALL_0DTE", "TSLA_PUT_SWING".
    Uses signal.expiry (a date) vs today to determine time bucket.
    """
    today = datetime.now().date()
    days_to_expiry = (signal.expiry - today).days

    if days_to_expiry == 0:
        time_label = "0DTE"
    elif days_to_expiry <= 3:
        time_label = "WEEKLY"
    else:
        time_label = "SWING"

    return f"{signal.symbol}_{signal.direction}_{time_label}"


# ─────────────────────────────────────────────
# Internal connection helper
# ─────────────────────────────────────────────

class _ConnectionCtx:
    """
    Context manager that wraps either a reused persistent connection
    (for :memory: DBs — each new connect() would create a blank slate)
    or a fresh per-call connection (for on-disk DBs, which share the
    same file so any connection sees the same data).
    """

    def __init__(self, db_path: str, persistent_conn: aiosqlite.Connection | None) -> None:
        self._db_path = db_path
        self._persistent = persistent_conn
        self._tmp: aiosqlite.Connection | None = None

    async def __aenter__(self) -> aiosqlite.Connection:
        if self._persistent is not None:
            return self._persistent
        self._tmp = await aiosqlite.connect(self._db_path)
        return self._tmp

    async def __aexit__(self, *_: object) -> None:
        if self._tmp is not None:
            await self._tmp.close()
            self._tmp = None


# ─────────────────────────────────────────────
# MemoryJournal
# ─────────────────────────────────────────────

_CREATE_TRADES = """
CREATE TABLE IF NOT EXISTS trades (
  trade_id              TEXT PRIMARY KEY,
  signal_id             TEXT NOT NULL,
  analyst_id            TEXT NOT NULL,
  symbol                TEXT NOT NULL,
  direction             TEXT NOT NULL,
  strike                REAL,
  expiry                TEXT,
  entry_price_per_share REAL,
  exit_price_per_share  REAL,
  qty                   INTEGER,
  pnl_per_share         REAL,
  pnl_pct               REAL,
  opened_at             TEXT,
  closed_at             TEXT,
  exit_reason           TEXT,
  evidence_json         TEXT,
  market_conditions     TEXT,
  outcome               TEXT
);
"""

_CREATE_ANALYST_STATS = """
CREATE TABLE IF NOT EXISTS analyst_stats (
  analyst_id   TEXT NOT NULL,
  pattern_type TEXT NOT NULL,
  win_count    INTEGER DEFAULT 0,
  loss_count   INTEGER DEFAULT 0,
  total_pnl    REAL DEFAULT 0.0,
  last_updated TEXT,
  PRIMARY KEY (analyst_id, pattern_type)
);
"""


class MemoryJournal:
    """
    Async SQLite journal for closed trades and per-analyst/pattern win-rate stats.

    Usage:
        journal = MemoryJournal()
        await journal.initialize()
        await journal.record_close(position, exit_price, "STOP_LOSS", market_conditions)

    Note: For :memory: databases (used in tests), a single persistent connection is
    kept open because each new aiosqlite.connect(":memory:") creates a brand-new
    empty database.  For on-disk paths the connection is opened/closed per operation
    so that multiple processes can share the file safely.
    """

    def __init__(self, db_path: str = "shared/state/memory.db") -> None:
        self.db_path = db_path
        # Persistent connection used only for :memory: databases.
        self._mem_conn: aiosqlite.Connection | None = None

    def _conn(self) -> _ConnectionCtx:
        return _ConnectionCtx(self.db_path, self._mem_conn)

    async def initialize(self) -> None:
        """Create tables if they do not already exist."""
        if self.db_path == ":memory:":
            # Open a persistent connection for the lifetime of this object.
            self._mem_conn = await aiosqlite.connect(":memory:")

        async with self._conn() as db:
            await db.execute(_CREATE_TRADES)
            await db.execute(_CREATE_ANALYST_STATS)
            await db.commit()

    async def close(self) -> None:
        """Explicitly close the persistent :memory: connection (if open)."""
        if self._mem_conn is not None:
            await self._mem_conn.close()
            self._mem_conn = None

    # ──────────────────────────────────────────
    # Write
    # ──────────────────────────────────────────

    async def record_close(
        self,
        position: PositionRecord,
        exit_price_per_share: float,
        exit_reason: str,
        market_conditions: dict | None = None,
        *,
        signal: Optional[TradeSignal] = None,
    ) -> None:
        """
        Compute PnL, determine outcome, insert into trades, upsert analyst_stats.

        Args:
            position: The PositionRecord being closed.
            exit_price_per_share: Actual fill price (per share / per option unit).
            exit_reason: Human-readable reason (STOP_LOSS, TARGET_HIT, SOURCE_SELL, etc.)
            market_conditions: Optional dict of market-context at close time.
            signal: Optional TradeSignal — used to derive pattern_type for analyst_stats.
                    If not supplied, pattern_type defaults to "<symbol>_<direction>_UNKNOWN".
        """
        if market_conditions is None:
            market_conditions = {}

        entry = position.avg_cost_per_share
        pnl_per_share = exit_price_per_share - entry
        pnl_pct = pnl_per_share / entry if entry != 0.0 else 0.0
        outcome = _compute_outcome(pnl_pct)

        now_iso = datetime.utcnow().isoformat()

        # Evidence — if the original signal is available serialise it; otherwise blank
        evidence_json: str
        if signal is not None:
            evidence_json = json.dumps([e.model_dump() for e in signal.evidence])
        else:
            evidence_json = "[]"

        # Derive pattern_type
        if signal is not None:
            pattern_type = _compute_pattern_type(signal)
        else:
            pattern_type = f"{position.symbol}_{position.direction}_UNKNOWN"

        async with self._conn() as db:
            # Insert trade row
            await db.execute(
                """
                INSERT OR REPLACE INTO trades (
                  trade_id, signal_id, analyst_id, symbol, direction,
                  strike, expiry, entry_price_per_share, exit_price_per_share,
                  qty, pnl_per_share, pnl_pct, opened_at, closed_at,
                  exit_reason, evidence_json, market_conditions, outcome
                ) VALUES (
                  ?, ?, ?, ?, ?,
                  ?, ?, ?, ?,
                  ?, ?, ?, ?, ?,
                  ?, ?, ?, ?
                )
                """,
                (
                    position.position_id,
                    position.signal_id,
                    position.analyst_id,
                    position.symbol,
                    position.direction,
                    position.strike,
                    position.expiry.isoformat(),
                    entry,
                    exit_price_per_share,
                    position.qty,
                    pnl_per_share,
                    pnl_pct,
                    position.opened_at.isoformat(),
                    now_iso,
                    exit_reason,
                    evidence_json,
                    json.dumps(market_conditions),
                    outcome,
                ),
            )

            # Upsert analyst_stats
            await db.execute(
                """
                INSERT INTO analyst_stats (analyst_id, pattern_type, win_count, loss_count, total_pnl, last_updated)
                VALUES (?, ?, 0, 0, 0.0, ?)
                ON CONFLICT(analyst_id, pattern_type) DO NOTHING
                """,
                (position.analyst_id, pattern_type, now_iso),
            )

            if outcome == "WIN":
                await db.execute(
                    """
                    UPDATE analyst_stats
                    SET win_count = win_count + 1,
                        total_pnl = total_pnl + ?,
                        last_updated = ?
                    WHERE analyst_id = ? AND pattern_type = ?
                    """,
                    (pnl_pct, now_iso, position.analyst_id, pattern_type),
                )
            elif outcome == "LOSS":
                await db.execute(
                    """
                    UPDATE analyst_stats
                    SET loss_count = loss_count + 1,
                        total_pnl = total_pnl + ?,
                        last_updated = ?
                    WHERE analyst_id = ? AND pattern_type = ?
                    """,
                    (pnl_pct, now_iso, position.analyst_id, pattern_type),
                )
            else:  # BREAKEVEN — count toward total_pnl only
                await db.execute(
                    """
                    UPDATE analyst_stats
                    SET total_pnl = total_pnl + ?,
                        last_updated = ?
                    WHERE analyst_id = ? AND pattern_type = ?
                    """,
                    (pnl_pct, now_iso, position.analyst_id, pattern_type),
                )

            await db.commit()

    # ──────────────────────────────────────────
    # Read — analyst-level
    # ──────────────────────────────────────────

    async def get_analyst_win_rate(
        self, analyst_id: str, min_trades: int = 5
    ) -> float | None:
        """
        Overall win-rate across all patterns for this analyst.

        Returns None if total decided trades (WIN + LOSS) < min_trades.
        BREAKEVEN trades are excluded from the denominator (they neither win nor lose).
        """
        async with self._conn() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT SUM(win_count) AS wins, SUM(loss_count) AS losses
                FROM analyst_stats
                WHERE analyst_id = ?
                """,
                (analyst_id,),
            ) as cursor:
                row = await cursor.fetchone()

        if row is None:
            return None

        wins = row["wins"] or 0
        losses = row["losses"] or 0
        total = wins + losses

        if total < min_trades:
            return None

        return wins / total

    # ──────────────────────────────────────────
    # Read — pattern-level
    # ──────────────────────────────────────────

    async def get_pattern_win_rate(self, analyst_id: str, pattern_type: str) -> dict:
        """
        Returns {win_rate: float, total_trades: int, avg_pnl_pct: float}
        for a specific (analyst, pattern) pair.

        total_trades counts rows in the trades table that match the pattern; win_rate
        and avg_pnl_pct are derived from analyst_stats for speed.
        """
        async with self._conn() as db:
            db.row_factory = aiosqlite.Row

            # Stats from the pre-aggregated table
            async with db.execute(
                """
                SELECT win_count, loss_count, total_pnl
                FROM analyst_stats
                WHERE analyst_id = ? AND pattern_type = ?
                """,
                (analyst_id, pattern_type),
            ) as cursor:
                stats_row = await cursor.fetchone()

        if stats_row is None:
            return {"win_rate": 0.0, "total_trades": 0, "avg_pnl_pct": 0.0}

        wins = stats_row["win_count"] or 0
        losses = stats_row["loss_count"] or 0
        total_pnl = stats_row["total_pnl"] or 0.0
        total_decided = wins + losses
        total_trades = total_decided  # BREAKEVEN rows not in stats counters

        win_rate = (wins / total_decided) if total_decided > 0 else 0.0
        avg_pnl_pct = (total_pnl / total_decided) if total_decided > 0 else 0.0

        return {
            "win_rate": win_rate,
            "total_trades": total_trades,
            "avg_pnl_pct": avg_pnl_pct,
        }

    # ──────────────────────────────────────────
    # Read — recent trades
    # ──────────────────────────────────────────

    async def get_recent_trades(self, analyst_id: str, days: int = 7) -> list[dict]:
        """
        Returns trades from the last N calendar days, sorted by closed_at desc.
        """
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        async with self._conn() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM trades
                WHERE analyst_id = ? AND closed_at >= ?
                ORDER BY closed_at DESC
                """,
                (analyst_id, cutoff),
            ) as cursor:
                rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    # ──────────────────────────────────────────
    # RL gate
    # ──────────────────────────────────────────

    async def should_reject_pattern(self, analyst_id: str, pattern_type: str) -> bool:
        """
        RL auto-reject gate.

        Returns True if:
          - (win_count + loss_count) >= _REJECT_MIN_TRADES (10), AND
          - win_rate < _REJECT_WIN_RATE (0.40)

        Analysts below the threshold lack sufficient history and are NOT auto-rejected.
        """
        async with self._conn() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT win_count, loss_count
                FROM analyst_stats
                WHERE analyst_id = ? AND pattern_type = ?
                """,
                (analyst_id, pattern_type),
            ) as cursor:
                row = await cursor.fetchone()

        if row is None:
            return False

        wins = row["win_count"] or 0
        losses = row["loss_count"] or 0
        total = wins + losses

        if total < _REJECT_MIN_TRADES:
            return False

        win_rate = wins / total
        return win_rate < _REJECT_WIN_RATE
