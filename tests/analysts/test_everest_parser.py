"""
Tests for analysts/discord/everest.py — Everest parser.

All tests use synthetic message dicts that mirror the actual Discord format
from the optionsbuftett trader in the Everest channel.

Real channel message format:
    HIGH CONFIDENCE 🎯
    6/12 $MCD 290c @.19
    1000  CONTRACTS

No live Discord connection required — pure unit tests on parse_everest_buy().
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from analysts.discord.everest import EverestBuySignal, parse_everest_buy


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _msg(content: str, author: str = "optionsbuftett", *, is_bot: bool = False) -> dict:
    return {
        "message_id": "111222333444",
        "channel_id": "1509430306749550653",
        "timestamp": "2026-06-14T09:00:00+00:00",
        "author_id": "9001",
        "author_name": author,
        "author_global_name": author,
        "is_bot": is_bot,
        "content_raw": content,
        "content": content,
        "embeds": [],
    }


_TODAY_YEAR = datetime.now(tz=timezone.utc).year


# ─── Buy signal: happy-path parsing ───────────────────────────────────────────

class TestParseBuySignal:
    """Core signal line parsing: M/D $TICKER STRIKE{c|p} @PRICE"""

    def test_high_confidence_call(self) -> None:
        """Canonical HIGH CONFIDENCE multi-line message — call option."""
        content = "HIGH CONFIDENCE 🎯\n6/12 $MCD 290c @.19\n1000  CONTRACTS @everyone"
        sig = parse_everest_buy(_msg(content))
        assert sig is not None
        assert sig.symbol == "MCD"
        assert sig.direction == "CALL"
        assert sig.strike == 290.0
        assert sig.price == 0.19

    def test_super_high_confidence_call(self) -> None:
        """SUPER HIGH CONFIDENCE variant."""
        content = "SUPER HIGH CONFIDENCE 🚨\n6/12 $PG 152.5c @.12\n1000  CONTRACTS"
        sig = parse_everest_buy(_msg(content))
        assert sig is not None
        assert sig.symbol == "PG"
        assert sig.direction == "CALL"
        assert sig.strike == 152.5
        assert sig.price == 0.12

    def test_added_heavy_call(self) -> None:
        """ADDED HEAVYYYY position-addition message."""
        content = "ADDED HEAVYYYY\n6/12 $PG 152.5c @.11\n1000  CONTRACTS @everyone"
        sig = parse_everest_buy(_msg(content))
        assert sig is not None
        assert sig.symbol == "PG"
        assert sig.strike == 152.5
        assert sig.price == 0.11

    def test_trade_alert_format(self) -> None:
        """$100,000 TRADE ALERT style message."""
        content = "$100,000 TRADE ALERT 🔥\n6/12 $PG 152.5c @.09\nADDED SUPER HEAVYYY"
        sig = parse_everest_buy(_msg(content))
        assert sig is not None
        assert sig.symbol == "PG"
        assert sig.price == 0.09

    def test_put_option(self) -> None:
        """Put option direction parsed correctly."""
        content = "HIGH CONFIDENCE 🎯\n6/14 $SPY 530p @.45"
        sig = parse_everest_buy(_msg(content))
        assert sig is not None
        assert sig.direction == "PUT"
        assert sig.symbol == "SPY"
        assert sig.strike == 530.0
        assert sig.price == 0.45

    def test_uppercase_direction_letter(self) -> None:
        """Direction letter C/P (uppercase) also accepted."""
        content = "HIGH CONFIDENCE 🎯\n6/14 $AAPL 200C @3.10"
        sig = parse_everest_buy(_msg(content))
        assert sig is not None
        assert sig.direction == "CALL"
        assert sig.price == 3.10

    def test_decimal_strike(self) -> None:
        """Decimal strikes like 152.5c parsed correctly."""
        content = "SUPER HIGH CONFIDENCE 🚨\n6/12 $PG 152.5c @.22\n1000  CONTRACTS"
        sig = parse_everest_buy(_msg(content))
        assert sig is not None
        assert sig.strike == 152.5

    def test_price_without_leading_digit(self) -> None:
        """Sub-penny prices like @.09 (no leading zero) parsed correctly."""
        content = "HIGH CONFIDENCE 🎯\n6/12 $MCD 290c @.09"
        sig = parse_everest_buy(_msg(content))
        assert sig is not None
        assert sig.price == pytest.approx(0.09)

    def test_whole_dollar_price(self) -> None:
        """Prices >= $1 like @2.50 parsed correctly."""
        content = "HIGH CONFIDENCE 🎯\n6/14 $TSLA 185c @2.50"
        sig = parse_everest_buy(_msg(content))
        assert sig is not None
        assert sig.price == 2.50

    def test_no_contracts_line_still_parsed(self) -> None:
        """Signal line without a CONTRACTS line is still valid."""
        content = "SUPER HIGH CONFIDENCE 🚨\n6/12 $MCD 290c @.22"
        sig = parse_everest_buy(_msg(content))
        assert sig is not None
        assert sig.contracts is None


# ─── Expiry parsing ───────────────────────────────────────────────────────────

class TestExpiryParsing:

    def test_expiry_parsed_from_signal_date(self) -> None:
        """The M/D date in the signal line becomes the expiry date."""
        content = "HIGH CONFIDENCE 🎯\n6/12 $MCD 290c @.19"
        sig = parse_everest_buy(_msg(content))
        assert sig is not None
        assert sig.expiry is not None
        assert sig.expiry.month == 6
        assert sig.expiry.day == 12
        assert sig.expiry.year == _TODAY_YEAR

    def test_expiry_single_digit_day(self) -> None:
        """M/D with single digit day (e.g. 6/5) parsed correctly."""
        content = "HIGH CONFIDENCE 🎯\n6/5 $NVDA 130c @.88"
        sig = parse_everest_buy(_msg(content))
        assert sig is not None
        assert sig.expiry is not None
        assert sig.expiry.month == 6
        assert sig.expiry.day == 5

    def test_expiry_double_digit_month_and_day(self) -> None:
        """Date like 12/20 still parsed correctly."""
        content = "HIGH CONFIDENCE 🎯\n12/20 $QQQ 480p @1.20"
        sig = parse_everest_buy(_msg(content))
        assert sig is not None
        assert sig.expiry is not None
        assert sig.expiry.month == 12
        assert sig.expiry.day == 20


# ─── Contract count parsing ───────────────────────────────────────────────────

class TestContractCount:

    def test_contract_count_parsed(self) -> None:
        """1000 CONTRACTS extracted as integer."""
        content = "HIGH CONFIDENCE 🎯\n6/12 $MCD 290c @.19\n1000  CONTRACTS"
        sig = parse_everest_buy(_msg(content))
        assert sig is not None
        assert sig.contracts == 1000

    def test_contract_count_not_present(self) -> None:
        """Missing CONTRACTS line → contracts=None."""
        content = "HIGH CONFIDENCE 🎯\n6/12 $MCD 290c @.19"
        sig = parse_everest_buy(_msg(content))
        assert sig is not None
        assert sig.contracts is None


# ─── Confidence label detection ───────────────────────────────────────────────

class TestConfidenceLabel:

    def test_super_high_label_and_confidence(self) -> None:
        content = "SUPER HIGH CONFIDENCE 🚨\n6/12 $PG 152.5c @.12"
        sig = parse_everest_buy(_msg(content))
        assert sig is not None
        assert sig.label == "SUPER_HIGH"
        assert sig.confidence == pytest.approx(0.82)

    def test_high_label_and_confidence(self) -> None:
        content = "HIGH CONFIDENCE 🎯\n6/12 $MCD 290c @.19"
        sig = parse_everest_buy(_msg(content))
        assert sig is not None
        assert sig.label == "HIGH"
        assert sig.confidence == pytest.approx(0.74)

    def test_trade_alert_label_and_confidence(self) -> None:
        content = "$100,000 TRADE ALERT 🔥\n6/12 $PG 152.5c @.09\nADDED SUPER HEAVYYY"
        sig = parse_everest_buy(_msg(content))
        assert sig is not None
        assert sig.label == "TRADE_ALERT"
        assert sig.confidence == pytest.approx(0.76)

    def test_added_label_and_confidence(self) -> None:
        content = "ADDED HEAVYYYY\n6/12 $PG 152.5c @.11\n1000  CONTRACTS"
        sig = parse_everest_buy(_msg(content))
        assert sig is not None
        assert sig.label == "ADDED"
        assert sig.confidence == pytest.approx(0.68)

    def test_unknown_label_and_confidence(self) -> None:
        """No confidence header → UNKNOWN label, lowest confidence."""
        content = "6/12 $MCD 290c @.19"
        sig = parse_everest_buy(_msg(content))
        assert sig is not None
        assert sig.label == "UNKNOWN"
        assert sig.confidence == pytest.approx(0.65)

    def test_super_high_takes_priority_over_high(self) -> None:
        """SUPER HIGH CONFIDENCE must not fall through to HIGH CONFIDENCE."""
        content = "SUPER HIGH CONFIDENCE 🚨\n6/12 $PG 152.5c @.22"
        sig = parse_everest_buy(_msg(content))
        assert sig is not None
        assert sig.label == "SUPER_HIGH"


# ─── Reject: exits and profit announcements ───────────────────────────────────

class TestRejectExits:

    def test_reject_sold_message(self) -> None:
        """SOLD keyword → exit message, must return None."""
        content = "$TGT @1.35 +1,000% 🔥🔥🔥\nSOLD MOST , LEFT RUNNERS"
        assert parse_everest_buy(_msg(content)) is None

    def test_reject_left_runners(self) -> None:
        content = "SOLD MOST, LEFT RUNNERS"
        assert parse_everest_buy(_msg(content)) is None

    def test_reject_gain_percentage(self) -> None:
        """+1,000% in message → profit announcement, must return None."""
        content = "$TGT @1.35 +1,000% 🔥🔥🔥"
        assert parse_everest_buy(_msg(content)) is None

    def test_reject_message_with_sold_even_if_signal_present(self) -> None:
        """If SOLD appears anywhere in message, reject regardless of signal line."""
        content = "HIGH CONFIDENCE 🎯\n6/12 $MCD 290c @.19\nSOLD ALREADY"
        assert parse_everest_buy(_msg(content)) is None


# ─── Reject: promotional spam ─────────────────────────────────────────────────

class TestRejectSpam:

    def test_reject_whop_url(self) -> None:
        content = "TODAY is your LAST CHANCE to lock in $600 LIFETIME ACCESS...\nhttps://whop.com/everest"
        assert parse_everest_buy(_msg(content)) is None

    def test_reject_final_notice(self) -> None:
        content = "🚨 FINAL NOTICE 🚨 Free alerts are PERMANENTLY SHUTTING DOWN..."
        assert parse_everest_buy(_msg(content)) is None

    def test_reject_final_warning(self) -> None:
        content = "FINAL WARNING — this is your last chance to join"
        assert parse_everest_buy(_msg(content)) is None

    def test_reject_shutting_down(self) -> None:
        content = "Free alerts are PERMANENTLY SHUTTING DOWN after tonight"
        assert parse_everest_buy(_msg(content)) is None

    def test_reject_lifetime_access(self) -> None:
        content = "Lock in $600 LIFETIME ACCESS before midnight"
        assert parse_everest_buy(_msg(content)) is None

    def test_reject_free_alerts_are(self) -> None:
        content = "FREE ALERTS ARE being shut down permanently 🚨"
        assert parse_everest_buy(_msg(content)) is None


# ─── Reject: non-signal messages ─────────────────────────────────────────────

class TestRejectNoSignal:

    def test_empty_content_returns_none(self) -> None:
        assert parse_everest_buy(_msg("")) is None

    def test_missing_content_key_returns_none(self) -> None:
        assert parse_everest_buy({"message_id": "000", "channel_id": "9999"}) is None

    def test_plain_commentary(self) -> None:
        assert parse_everest_buy(_msg("Watching MCD, might play it later")) is None

    def test_missing_at_price(self) -> None:
        """Signal line without @price should NOT match."""
        assert parse_everest_buy(_msg("6/12 $MCD 290c")) is None

    def test_missing_dollar_ticker(self) -> None:
        """Signal line without $ prefix on ticker should NOT match."""
        assert parse_everest_buy(_msg("6/12 MCD 290c @.19")) is None

    def test_missing_date_prefix(self) -> None:
        """Signal line without date should NOT match."""
        assert parse_everest_buy(_msg("$MCD 290c @.19")) is None

    def test_emoji_only_message(self) -> None:
        assert parse_everest_buy(_msg("🔥🔥🔥")) is None

    def test_generic_market_comment(self) -> None:
        assert parse_everest_buy(_msg("Market looking strong today. SPY could rip.")) is None


# ─── Author filter ────────────────────────────────────────────────────────────

class TestAuthorFilter:
    """Any author is accepted — the content pattern is the only gate."""

    def test_expected_author_optionsbuftett(self) -> None:
        content = "HIGH CONFIDENCE 🎯\n6/12 $MCD 290c @.19"
        sig = parse_everest_buy(_msg(content, author="optionsbuftett"))
        assert sig is not None

    def test_any_other_author_also_accepted(self) -> None:
        """No author restriction — content pattern gates."""
        content = "HIGH CONFIDENCE 🎯\n6/12 $MCD 290c @.19"
        sig = parse_everest_buy(_msg(content, author="warrenbuffett."))
        assert sig is not None

    def test_bot_author_accepted(self) -> None:
        content = "HIGH CONFIDENCE 🎯\n6/12 $MCD 290c @.19"
        sig = parse_everest_buy(_msg(content, author="SomeBot", is_bot=True))
        assert sig is not None


# ─── Metadata propagation ─────────────────────────────────────────────────────

class TestMetadataPropagation:

    def test_channel_id_propagated(self) -> None:
        msg = _msg("HIGH CONFIDENCE 🎯\n6/12 $MCD 290c @.19")
        msg["channel_id"] = "1509430306749550653"
        sig = parse_everest_buy(msg)
        assert sig is not None
        assert sig.channel_id == "1509430306749550653"

    def test_message_id_propagated(self) -> None:
        msg = _msg("HIGH CONFIDENCE 🎯\n6/12 $MCD 290c @.19")
        msg["message_id"] = "987654321"
        sig = parse_everest_buy(msg)
        assert sig is not None
        assert sig.message_id == "987654321"

    def test_raw_content_propagated(self) -> None:
        content = "HIGH CONFIDENCE 🎯\n6/12 $MCD 290c @.19\n1000  CONTRACTS"
        sig = parse_everest_buy(_msg(content))
        assert sig is not None
        assert sig.raw_content == content

    def test_returns_everest_buy_signal_type(self) -> None:
        content = "HIGH CONFIDENCE 🎯\n6/12 $MCD 290c @.19"
        sig = parse_everest_buy(_msg(content))
        assert isinstance(sig, EverestBuySignal)
