"""
Tests for analysts/discord/albert.py parser functions.

All tests use synthetic message dicts that mirror the scraped Discord format.
No live Discord connection required — pure unit tests.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from analysts.discord.albert import (
    BuySignal,
    _EARNINGS_WINDOW_DAYS,
    is_earnings_period,
    parse_albert_buy,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _albert_msg(content: str, author: str = "albert [BOT]", is_bot: bool = True) -> dict:
    return {
        "message_id": "999",
        "channel_id": "1234567890",
        "timestamp": "2026-06-13T14:00:00+00:00",
        "author_id": "5001",
        "author_name": author,
        "author_global_name": author,
        "is_bot": is_bot,
        "content_raw": content,
        "content": content,
        "embeds": [],
    }


def _calendar_json(entries: dict[str, str]) -> str:
    return json.dumps(entries)


# ─── parse_albert_buy ─────────────────────────────────────────────────────────

class TestParseAlbertBuy:
    def test_call_basic(self) -> None:
        msg = _albert_msg("Bought AAPL 210C at 3.50")
        sig = parse_albert_buy(msg)
        assert sig is not None
        assert sig.symbol == "AAPL"
        assert sig.direction == "CALL"
        assert sig.strike == 210.0
        assert sig.price == 3.50

    def test_put_basic(self) -> None:
        msg = _albert_msg("Bought NVDA 900P at 6.20 Earnings play")
        sig = parse_albert_buy(msg)
        assert sig is not None
        assert sig.symbol == "NVDA"
        assert sig.direction == "PUT"
        assert sig.strike == 900.0
        assert sig.price == 6.20

    def test_bougth_typo_call(self) -> None:
        """'Bougth' typo must be handled identically to 'Bought'."""
        msg = _albert_msg("Bougth MSFT 450C at 4.80 Earnings")
        sig = parse_albert_buy(msg)
        assert sig is not None
        assert sig.symbol == "MSFT"
        assert sig.direction == "CALL"
        assert sig.strike == 450.0
        assert sig.price == 4.80

    def test_bougth_typo_put(self) -> None:
        msg = _albert_msg("Bougth TSLA 250P at 2.10")
        sig = parse_albert_buy(msg)
        assert sig is not None
        assert sig.symbol == "TSLA"
        assert sig.direction == "PUT"

    def test_decimal_strike(self) -> None:
        msg = _albert_msg("Bought AAPL 212.5C at 1.90")
        sig = parse_albert_buy(msg)
        assert sig is not None
        assert sig.strike == 212.5

    def test_decimal_price(self) -> None:
        msg = _albert_msg("Bought AMZN 195C at 5.75")
        sig = parse_albert_buy(msg)
        assert sig is not None
        assert sig.price == 5.75

    def test_symbol_uppercase(self) -> None:
        """Symbol must be returned uppercase regardless of message case."""
        # The regex uses IGNORECASE but the symbol group is uppercased in parser.
        msg = _albert_msg("Bought GOOG 180C at 3.00")
        sig = parse_albert_buy(msg)
        assert sig is not None
        assert sig.symbol == "GOOG"

    def test_expiry_is_none_by_default(self) -> None:
        """Albert messages don't include expiry — should be None."""
        msg = _albert_msg("Bought META 560C at 8.00")
        sig = parse_albert_buy(msg)
        assert sig is not None
        assert sig.expiry is None

    def test_channel_id_captured(self) -> None:
        msg = _albert_msg("Bought AAPL 210C at 3.50")
        sig = parse_albert_buy(msg)
        assert sig is not None
        assert sig.channel_id == "1234567890"

    def test_message_id_captured(self) -> None:
        msg = _albert_msg("Bought AAPL 210C at 3.50")
        sig = parse_albert_buy(msg)
        assert sig is not None
        assert sig.message_id == "999"

    def test_raw_content_captured(self) -> None:
        content = "Bought AAPL 210C at 3.50 Strong earnings expected"
        msg = _albert_msg(content)
        sig = parse_albert_buy(msg)
        assert sig is not None
        assert sig.raw_content == content

    def test_wrong_author_rejected(self) -> None:
        """Messages from non-albert authors must return None."""
        msg = _albert_msg("Bought AAPL 210C at 3.50", author="random_person")
        assert parse_albert_buy(msg) is None

    def test_infra_bot_rejected(self) -> None:
        """INFRA bot (Vinod's bot) must not be parsed by Albert."""
        msg = _albert_msg("Bought AAPL 210C at 3.50", author="INFRA TRADE ALERT [BOT]")
        assert parse_albert_buy(msg) is None

    def test_non_bot_rejected(self) -> None:
        """Non-bot messages must return None even if author name matches."""
        msg = _albert_msg("Bought AAPL 210C at 3.50", is_bot=False)
        assert parse_albert_buy(msg) is None

    def test_no_buy_pattern_returns_none(self) -> None:
        """Messages with no buy pattern must return None."""
        msg = _albert_msg("Sold AAPL 210C at 5.00")
        assert parse_albert_buy(msg) is None

    def test_random_text_returns_none(self) -> None:
        msg = _albert_msg("Good morning! Earnings season is here.")
        assert parse_albert_buy(msg) is None

    def test_five_char_symbol(self) -> None:
        """Symbols up to 5 characters must be accepted."""
        msg = _albert_msg("Bought GOOGL 180C at 4.50")
        sig = parse_albert_buy(msg)
        assert sig is not None
        assert sig.symbol == "GOOGL"

    def test_albert_case_insensitive_in_author(self) -> None:
        """Author check is case-insensitive for 'albert'."""
        msg = _albert_msg("Bought AAPL 210C at 3.50", author="ALBERT [BOT]")
        sig = parse_albert_buy(msg)
        assert sig is not None

    def test_author_global_name_checked(self) -> None:
        """author_global_name takes precedence over author_name."""
        msg = _albert_msg("Bought AAPL 210C at 3.50", author="random")
        msg["author_global_name"] = "albert earnings [BOT]"
        sig = parse_albert_buy(msg)
        assert sig is not None

    def test_integer_price(self) -> None:
        msg = _albert_msg("Bought AAPL 210C at 4")
        sig = parse_albert_buy(msg)
        assert sig is not None
        assert sig.price == 4.0

    def test_integer_strike(self) -> None:
        msg = _albert_msg("Bought AAPL 210C at 3.50")
        sig = parse_albert_buy(msg)
        assert sig is not None
        assert sig.strike == 210.0


# ─── is_earnings_period ───────────────────────────────────────────────────────

class TestIsEarningsPeriod:
    def test_within_window_returns_true(self, tmp_path: Path) -> None:
        """Symbol with earnings 5 days from today → True."""
        today = datetime.now(tz=timezone.utc).date()
        earnings = today + timedelta(days=5)
        calendar = {"AAPL": earnings.isoformat()}
        cal_path = tmp_path / "earnings_calendar.json"
        cal_path.write_text(json.dumps(calendar))

        with patch("analysts.discord.albert._EARNINGS_CALENDAR_PATH", cal_path):
            assert is_earnings_period("AAPL") is True

    def test_outside_window_returns_false(self, tmp_path: Path) -> None:
        """Symbol with earnings 30 days from today → False."""
        today = datetime.now(tz=timezone.utc).date()
        earnings = today + timedelta(days=30)
        calendar = {"AAPL": earnings.isoformat()}
        cal_path = tmp_path / "earnings_calendar.json"
        cal_path.write_text(json.dumps(calendar))

        with patch("analysts.discord.albert._EARNINGS_CALENDAR_PATH", cal_path):
            assert is_earnings_period("AAPL") is False

    def test_earnings_today_returns_true(self, tmp_path: Path) -> None:
        """Symbol with earnings today → True."""
        today = datetime.now(tz=timezone.utc).date()
        calendar = {"AAPL": today.isoformat()}
        cal_path = tmp_path / "earnings_calendar.json"
        cal_path.write_text(json.dumps(calendar))

        with patch("analysts.discord.albert._EARNINGS_CALENDAR_PATH", cal_path):
            assert is_earnings_period("AAPL") is True

    def test_earnings_past_within_window_returns_true(self, tmp_path: Path) -> None:
        """Symbol with earnings 10 days ago → True (within ±14 day window)."""
        today = datetime.now(tz=timezone.utc).date()
        earnings = today - timedelta(days=10)
        calendar = {"AAPL": earnings.isoformat()}
        cal_path = tmp_path / "earnings_calendar.json"
        cal_path.write_text(json.dumps(calendar))

        with patch("analysts.discord.albert._EARNINGS_CALENDAR_PATH", cal_path):
            assert is_earnings_period("AAPL") is True

    def test_earnings_past_outside_window_returns_false(self, tmp_path: Path) -> None:
        """Symbol with earnings 20 days ago → False."""
        today = datetime.now(tz=timezone.utc).date()
        earnings = today - timedelta(days=20)
        calendar = {"AAPL": earnings.isoformat()}
        cal_path = tmp_path / "earnings_calendar.json"
        cal_path.write_text(json.dumps(calendar))

        with patch("analysts.discord.albert._EARNINGS_CALENDAR_PATH", cal_path):
            assert is_earnings_period("AAPL") is False

    def test_symbol_not_in_calendar_fail_open(self, tmp_path: Path) -> None:
        """Symbol missing from calendar → fail-open (True)."""
        calendar = {"MSFT": "2026-07-22"}
        cal_path = tmp_path / "earnings_calendar.json"
        cal_path.write_text(json.dumps(calendar))

        with patch("analysts.discord.albert._EARNINGS_CALENDAR_PATH", cal_path):
            assert is_earnings_period("AAPL") is True

    def test_missing_calendar_file_fail_open(self, tmp_path: Path) -> None:
        """Missing calendar file → fail-open (True)."""
        nonexistent = tmp_path / "does_not_exist.json"
        with patch("analysts.discord.albert._EARNINGS_CALENDAR_PATH", nonexistent):
            assert is_earnings_period("AAPL") is True

    def test_malformed_json_fail_open(self, tmp_path: Path) -> None:
        """Corrupted calendar file → fail-open (True)."""
        cal_path = tmp_path / "earnings_calendar.json"
        cal_path.write_text("this is not valid json {{{{")

        with patch("analysts.discord.albert._EARNINGS_CALENDAR_PATH", cal_path):
            assert is_earnings_period("AAPL") is True

    def test_invalid_date_format_fail_open(self, tmp_path: Path) -> None:
        """Invalid date string for symbol → fail-open (True)."""
        calendar = {"AAPL": "not-a-date"}
        cal_path = tmp_path / "earnings_calendar.json"
        cal_path.write_text(json.dumps(calendar))

        with patch("analysts.discord.albert._EARNINGS_CALENDAR_PATH", cal_path):
            assert is_earnings_period("AAPL") is True

    def test_symbol_lookup_case_insensitive(self, tmp_path: Path) -> None:
        """Symbol lookup is case-insensitive (calendar key is uppercased)."""
        today = datetime.now(tz=timezone.utc).date()
        earnings = today + timedelta(days=3)
        calendar = {"AAPL": earnings.isoformat()}
        cal_path = tmp_path / "earnings_calendar.json"
        cal_path.write_text(json.dumps(calendar))

        with patch("analysts.discord.albert._EARNINGS_CALENDAR_PATH", cal_path):
            # Lowercase symbol passed → should still find "AAPL" key
            assert is_earnings_period("aapl") is True

    def test_exactly_at_window_boundary_returns_true(self, tmp_path: Path) -> None:
        """Exactly 14 days away → True (boundary is inclusive)."""
        today = datetime.now(tz=timezone.utc).date()
        earnings = today + timedelta(days=_EARNINGS_WINDOW_DAYS)
        calendar = {"AAPL": earnings.isoformat()}
        cal_path = tmp_path / "earnings_calendar.json"
        cal_path.write_text(json.dumps(calendar))

        with patch("analysts.discord.albert._EARNINGS_CALENDAR_PATH", cal_path):
            assert is_earnings_period("AAPL") is True

    def test_one_day_outside_window_returns_false(self, tmp_path: Path) -> None:
        """15 days away → False (just outside the 14-day boundary)."""
        today = datetime.now(tz=timezone.utc).date()
        earnings = today + timedelta(days=_EARNINGS_WINDOW_DAYS + 1)
        calendar = {"AAPL": earnings.isoformat()}
        cal_path = tmp_path / "earnings_calendar.json"
        cal_path.write_text(json.dumps(calendar))

        with patch("analysts.discord.albert._EARNINGS_CALENDAR_PATH", cal_path):
            assert is_earnings_period("AAPL") is False

    def test_multiple_symbols_in_calendar(self, tmp_path: Path) -> None:
        """Calendar with multiple symbols — only the queried symbol is checked."""
        today = datetime.now(tz=timezone.utc).date()
        calendar = {
            "AAPL": (today + timedelta(days=5)).isoformat(),
            "MSFT": (today + timedelta(days=30)).isoformat(),
            "NVDA": (today - timedelta(days=25)).isoformat(),
        }
        cal_path = tmp_path / "earnings_calendar.json"
        cal_path.write_text(json.dumps(calendar))

        with patch("analysts.discord.albert._EARNINGS_CALENDAR_PATH", cal_path):
            assert is_earnings_period("AAPL") is True   # 5 days out
            assert is_earnings_period("MSFT") is False  # 30 days out
            assert is_earnings_period("NVDA") is False  # 25 days past
