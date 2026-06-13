"""
Tests for analysts/discord/everest.py parser function.

All tests use synthetic message dicts that mirror the Discord format.
No live Discord connection required — pure unit tests.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from analysts.discord.everest import EverestBuySignal, parse_everest_buy


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _msg(content: str, author: str = "EverestTrader", *, is_bot: bool = False) -> dict:
    return {
        "message_id": "333",
        "channel_id": "9999999999999999999",
        "timestamp": "2026-06-13T14:00:00+00:00",
        "author_id": "5001",
        "author_name": author,
        "author_global_name": author,
        "is_bot": is_bot,
        "content_raw": content,
        "content": content,
        "embeds": [],
    }


# ─── Buy pattern tests ────────────────────────────────────────────────────────

class TestParseEverestBuy:

    # --- "Buying" keyword ---

    def test_buying_call(self) -> None:
        msg = _msg("Buying TSLA 430C at 1.70")
        sig = parse_everest_buy(msg)
        assert sig is not None
        assert sig.symbol == "TSLA"
        assert sig.direction == "CALL"
        assert sig.strike == 430.0
        assert sig.price == 1.70

    def test_buying_put(self) -> None:
        msg = _msg("Buying SPY 735P at 2.50")
        sig = parse_everest_buy(msg)
        assert sig is not None
        assert sig.symbol == "SPY"
        assert sig.direction == "PUT"
        assert sig.strike == 735.0
        assert sig.price == 2.50

    def test_buying_with_at_sign(self) -> None:
        """'@' as alias for 'at' in price."""
        msg = _msg("Buying AAPL 200C @ 3.10")
        sig = parse_everest_buy(msg)
        assert sig is not None
        assert sig.symbol == "AAPL"
        assert sig.strike == 200.0
        assert sig.price == 3.10

    def test_buying_with_expiry(self) -> None:
        msg = _msg("Buying MSFT 455C at 4.80 exp 06/20/2026")
        sig = parse_everest_buy(msg)
        assert sig is not None
        assert sig.expiry == date(2026, 6, 20)

    def test_buying_without_expiry(self) -> None:
        msg = _msg("Buying NVDA 1200C at 10.50")
        sig = parse_everest_buy(msg)
        assert sig is not None
        assert sig.expiry is None

    # --- "Added" / "Add" keyword ---

    def test_added_call(self) -> None:
        msg = _msg("Added AMD 180C at 1.20")
        sig = parse_everest_buy(msg)
        assert sig is not None
        assert sig.symbol == "AMD"
        assert sig.direction == "CALL"
        assert sig.strike == 180.0
        assert sig.price == 1.20

    def test_added_with_exp_keyword(self) -> None:
        msg = _msg("Added AMZN 185C at 5.00 exp 06/27")
        sig = parse_everest_buy(msg)
        assert sig is not None
        assert sig.symbol == "AMZN"
        # Expiry parsed as MM/DD with current year
        assert sig.expiry is not None
        assert sig.expiry.month == 6
        assert sig.expiry.day == 27

    # --- "Bought" / "Bougth" keyword ---

    def test_bought_basic(self) -> None:
        msg = _msg("Bought QQQ 480P at 3.40")
        sig = parse_everest_buy(msg)
        assert sig is not None
        assert sig.symbol == "QQQ"
        assert sig.direction == "PUT"
        assert sig.strike == 480.0
        assert sig.price == 3.40

    def test_bougth_typo(self) -> None:
        """Common typo 'Bougth' must be handled identically to 'Bought'."""
        msg = _msg("Bougth TSLA 440C at 2.10")
        sig = parse_everest_buy(msg)
        assert sig is not None
        assert sig.symbol == "TSLA"
        assert sig.direction == "CALL"
        assert sig.strike == 440.0
        assert sig.price == 2.10

    # --- @here prefix (no explicit keyword) ---

    def test_at_here_prefix(self) -> None:
        msg = _msg("@here AAPL 200C at 3.10")
        sig = parse_everest_buy(msg)
        assert sig is not None
        assert sig.symbol == "AAPL"
        assert sig.direction == "CALL"
        assert sig.strike == 200.0
        assert sig.price == 3.10

    def test_at_here_with_buying_keyword(self) -> None:
        msg = _msg("@here Buying SPX 5500C at 8.00")
        sig = parse_everest_buy(msg)
        assert sig is not None
        assert sig.symbol == "SPX"
        assert sig.strike == 5500.0

    def test_at_here_put(self) -> None:
        msg = _msg("@here SPY 740P at 1.80")
        sig = parse_everest_buy(msg)
        assert sig is not None
        assert sig.direction == "PUT"
        assert sig.price == 1.80

    # --- Expiry parsing ---

    def test_expiry_full_date(self) -> None:
        msg = _msg("Buying TSLA 430C at 1.70 expiry 07/18/2026")
        sig = parse_everest_buy(msg)
        assert sig is not None
        assert sig.expiry == date(2026, 7, 18)

    def test_expiry_two_digit_year(self) -> None:
        msg = _msg("Buying TSLA 430C at 1.70 exp 07/18/26")
        sig = parse_everest_buy(msg)
        assert sig is not None
        assert sig.expiry is not None
        assert sig.expiry.month == 7
        assert sig.expiry.day == 18

    def test_expiry_mm_dd_only(self) -> None:
        msg = _msg("Buying AAPL 200C at 3.00 exp 08/15")
        sig = parse_everest_buy(msg)
        assert sig is not None
        assert sig.expiry is not None
        today_year = datetime.now(tz=timezone.utc).year
        assert sig.expiry.year == today_year
        assert sig.expiry.month == 8
        assert sig.expiry.day == 15

    # --- Decimal strike ---

    def test_decimal_strike(self) -> None:
        msg = _msg("Buying SPX 5525.5C at 4.20")
        sig = parse_everest_buy(msg)
        assert sig is not None
        assert sig.strike == 5525.5

    # --- Non-matching messages return None ---

    def test_no_buy_keyword_no_at_here(self) -> None:
        """No prefix and no @here — must return None."""
        msg = _msg("TSLA 430C at 1.70")
        assert parse_everest_buy(msg) is None

    def test_plain_commentary(self) -> None:
        msg = _msg("Watching TSLA closely, might buy if it breaks 430")
        assert parse_everest_buy(msg) is None

    def test_sell_message_not_matched(self) -> None:
        msg = _msg("Sold TSLA 430C at 3.20")
        assert parse_everest_buy(msg) is None

    def test_empty_content_returns_none(self) -> None:
        msg = _msg("")
        assert parse_everest_buy(msg) is None

    def test_missing_content_key_returns_none(self) -> None:
        msg = {
            "message_id": "000",
            "channel_id": "9999",
        }
        assert parse_everest_buy(msg) is None

    def test_price_analysis_commentary(self) -> None:
        """'Looking at 430C' must not match — no buy action word."""
        msg = _msg("Looking at TSLA 430C, might be good at 1.70")
        assert parse_everest_buy(msg) is None

    def test_stoploss_commentary_not_matched(self) -> None:
        msg = _msg("Stop at 1.20 on TSLA 430C")
        assert parse_everest_buy(msg) is None

    # --- Author filter: any author accepted ---

    def test_any_author_accepted(self) -> None:
        """Everest has no bot filter — any author is accepted."""
        msg = _msg("Buying TSLA 430C at 1.70", author="RandomUser123")
        sig = parse_everest_buy(msg)
        assert sig is not None

    def test_bot_author_accepted(self) -> None:
        """Bot messages are also accepted."""
        msg = _msg("Buying TSLA 430C at 1.70", author="SomeBot", is_bot=True)
        sig = parse_everest_buy(msg)
        assert sig is not None

    # --- Message metadata propagation ---

    def test_channel_id_propagated(self) -> None:
        msg = _msg("Buying TSLA 430C at 1.70")
        msg["channel_id"] = "8888777766665555"
        sig = parse_everest_buy(msg)
        assert sig is not None
        assert sig.channel_id == "8888777766665555"

    def test_message_id_propagated(self) -> None:
        msg = _msg("Buying TSLA 430C at 1.70")
        msg["message_id"] = "111222333"
        sig = parse_everest_buy(msg)
        assert sig is not None
        assert sig.message_id == "111222333"

    def test_raw_content_propagated(self) -> None:
        content = "Buying TSLA 430C at 1.70 exp 06/20/2026"
        msg = _msg(content)
        sig = parse_everest_buy(msg)
        assert sig is not None
        assert sig.raw_content == content
