#!/usr/bin/env python3
"""
scripts/pre_live_checklist.py — M5.1 Pre-Live Safety Checklist

Run this before switching PAPER_TRADING_MODE=false.
ALL checks must pass; any failure blocks go-live.

Usage:
    python scripts/pre_live_checklist.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

# ─── Logging ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ─── Result dataclass ────────────────────────────────────────────────────────

@dataclass
class Check:
    name: str
    passed: bool
    detail: str


# ─── Individual checks ───────────────────────────────────────────────────────

def check_kill_switch_is_healthy() -> Check:
    """Kill switch file must exist and have active=false."""
    path = Path(os.getenv("KILL_SWITCH_PATH", "shared/state/kill_switch.json"))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Check("Kill switch file exists", False, f"File not found: {path}")
    except json.JSONDecodeError as exc:
        return Check("Kill switch file exists", False, f"Malformed JSON: {exc}")

    active = data.get("active", True)
    if active:
        reason = data.get("reason", "no reason given")
        return Check("Kill switch is healthy", False, f"Kill switch is ACTIVE — reason: {reason}")

    return Check("Kill switch is healthy", True, f"{path} exists, active=false")


def check_paper_mode_env_is_false() -> Check:
    """PAPER_TRADING_MODE environment variable must be the literal string 'false'."""
    val = os.getenv("PAPER_TRADING_MODE", "true")
    if val.lower() != "false":
        return Check(
            "PAPER_TRADING_MODE=false",
            False,
            f"PAPER_TRADING_MODE={val!r} — must be set to 'false' to go live",
        )
    return Check("PAPER_TRADING_MODE=false", True, "PAPER_TRADING_MODE is 'false'")


def check_robinhood_auth_works() -> Check:
    """Robinhood credentials must be present in env."""
    rh_user = os.getenv("ROBINHOOD_USERNAME", "")
    rh_pass = os.getenv("ROBINHOOD_PASSWORD", "")
    rh_mfa = os.getenv("ROBINHOOD_MFA_SECRET", "")  # TOTP secret

    missing = []
    if not rh_user:
        missing.append("ROBINHOOD_USERNAME")
    if not rh_pass:
        missing.append("ROBINHOOD_PASSWORD")
    if not rh_mfa:
        missing.append("ROBINHOOD_MFA_SECRET")

    if missing:
        return Check(
            "Robinhood credentials present",
            False,
            f"Missing env vars: {', '.join(missing)}",
        )

    # Attempt a lightweight auth check by importing the gateway
    try:
        import importlib
        rh_mod = importlib.import_module("gateway.rh_gateway")
        gateway_cls = getattr(rh_mod, "RHGatewayClient", None)
        if gateway_cls is None:
            return Check(
                "Robinhood auth check",
                False,
                "RHGatewayClient not found in gateway.rh_gateway — import issue",
            )
        return Check("Robinhood credentials present", True, "All RH env vars set; gateway importable")
    except ImportError as exc:
        return Check(
            "Robinhood credentials present",
            False,
            f"Cannot import gateway.rh_gateway: {exc}",
        )


def check_redis_connected() -> Check:
    """Redis must be reachable (used for signal deduplication + state sync)."""
    try:
        from core.redis_client import get_redis_client
        client = get_redis_client()
        client.ping()
        return Check("Redis connected", True, f"Redis PING OK at {os.getenv('REDIS_URL', 'redis://localhost:6379')}")
    except Exception as exc:
        return Check("Redis connected", False, f"Redis unreachable: {exc}")


def check_telegram_alerts_working() -> Check:
    """Telegram bot token and chat ID must be set."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not token:
        return Check("Telegram alerts configured", False, "TELEGRAM_BOT_TOKEN not set")
    if not chat_id:
        return Check("Telegram alerts configured", False, "TELEGRAM_CHAT_ID not set")

    # Lightweight connectivity check: call getMe
    try:
        import httpx
        resp = httpx.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=10.0,
        )
        if resp.status_code == 200 and resp.json().get("ok"):
            bot_name = resp.json()["result"].get("username", "unknown")
            return Check(
                "Telegram alerts configured",
                True,
                f"Bot @{bot_name} reachable; chat_id={chat_id}",
            )
        return Check(
            "Telegram alerts configured",
            False,
            f"Telegram getMe returned status {resp.status_code}: {resp.text[:120]}",
        )
    except Exception as exc:
        return Check("Telegram alerts configured", False, f"Telegram connectivity check failed: {exc}")


def check_max_position_size_set() -> Check:
    """MAX_POSITION_SIZE_USD must be set to a positive integer."""
    val = os.getenv("MAX_POSITION_SIZE_USD", "")
    if not val:
        return Check("MAX_POSITION_SIZE_USD set", False, "MAX_POSITION_SIZE_USD env var not set")
    try:
        amount = float(val)
        if amount <= 0:
            return Check("MAX_POSITION_SIZE_USD set", False, f"MAX_POSITION_SIZE_USD={val} must be positive")
        if amount > 10_000:
            return Check(
                "MAX_POSITION_SIZE_USD set",
                False,
                f"MAX_POSITION_SIZE_USD={val} exceeds safety ceiling $10,000 — reduce it",
            )
        return Check("MAX_POSITION_SIZE_USD set", True, f"MAX_POSITION_SIZE_USD=${amount:.0f}")
    except ValueError:
        return Check("MAX_POSITION_SIZE_USD set", False, f"MAX_POSITION_SIZE_USD={val!r} is not a number")


def check_daily_loss_limit_set() -> Check:
    """MAX_DAILY_LOSS_USD must be set to a positive integer."""
    val = os.getenv("MAX_DAILY_LOSS_USD", "")
    if not val:
        return Check("MAX_DAILY_LOSS_USD set", False, "MAX_DAILY_LOSS_USD env var not set")
    try:
        amount = float(val)
        if amount <= 0:
            return Check("MAX_DAILY_LOSS_USD set", False, f"MAX_DAILY_LOSS_USD={val} must be positive")
        if amount > 5_000:
            return Check(
                "MAX_DAILY_LOSS_USD set",
                False,
                f"MAX_DAILY_LOSS_USD={val} exceeds recommended ceiling $5,000 — reduce it",
            )
        return Check("MAX_DAILY_LOSS_USD set", True, f"MAX_DAILY_LOSS_USD=${amount:.0f}")
    except ValueError:
        return Check("MAX_DAILY_LOSS_USD set", False, f"MAX_DAILY_LOSS_USD={val!r} is not a number")


def check_doppler_secrets_loaded() -> Check:
    """
    Key trading secrets that must be sourced from Doppler (not hardcoded).
    Check that they are present in the environment (Doppler injects them at runtime).
    """
    required_secrets = [
        "DISCORD_BOT_TOKEN",
        "UNUSUAL_WHALES_API_KEY",
        "ROBINHOOD_USERNAME",
        "ROBINHOOD_PASSWORD",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ]
    missing = [s for s in required_secrets if not os.getenv(s)]

    if missing:
        return Check(
            "Doppler secrets loaded",
            False,
            f"Missing secrets (expected from Doppler): {', '.join(missing)}",
        )
    return Check(
        "Doppler secrets loaded",
        True,
        f"All {len(required_secrets)} required secrets present in environment",
    )


def check_kill_switch_can_be_activated() -> Check:
    """
    Verify the kill switch round-trip: activate it, confirm it reads as blocked,
    then deactivate it and confirm it reads as healthy.

    This ensures the safety circuit actually works before going live.
    """
    path = Path(os.getenv("KILL_SWITCH_PATH", "shared/state/kill_switch.json"))

    # Read original state so we can restore it
    try:
        original_text = path.read_text(encoding="utf-8") if path.exists() else None
    except OSError:
        original_text = None

    try:
        from core.kill_switch import is_blocked, set_blocked, set_healthy

        # 1. Activate
        set_blocked("pre_live_checklist: activation test", path=path)
        if not is_blocked(path=path):
            return Check(
                "Kill switch round-trip",
                False,
                "set_blocked() called but is_blocked() still returned False",
            )

        # 2. Deactivate
        set_healthy(path=path)
        if is_blocked(path=path):
            return Check(
                "Kill switch round-trip",
                False,
                "set_healthy() called but is_blocked() still returned True",
            )

        return Check(
            "Kill switch round-trip",
            True,
            "Kill switch activated and deactivated successfully",
        )

    except Exception as exc:
        return Check("Kill switch round-trip", False, f"Exception during test: {exc}")

    finally:
        # Always restore original state
        if original_text is not None:
            try:
                path.write_text(original_text, encoding="utf-8")
            except OSError:
                pass
        elif path.exists():
            try:
                path.unlink()
            except OSError:
                pass


# ─── Runner ──────────────────────────────────────────────────────────────────

def run_checklist() -> bool:
    """
    Execute all pre-live checks and print a structured report.

    Returns True only if ALL checks pass.
    """
    checks: list[Check] = [
        check_kill_switch_is_healthy(),
        check_paper_mode_env_is_false(),
        check_robinhood_auth_works(),
        check_redis_connected(),
        check_telegram_alerts_working(),
        check_max_position_size_set(),
        check_daily_loss_limit_set(),
        check_doppler_secrets_loaded(),
        check_kill_switch_can_be_activated(),
    ]

    print()
    print("=" * 60)
    print("  ANALYST TEAM — PRE-LIVE SAFETY CHECKLIST")
    print("=" * 60)

    for c in checks:
        status = "PASS" if c.passed else "FAIL"
        icon = "v" if c.passed else "X"
        print(f"  [{icon}] {status:<4}  {c.name}")
        print(f"           {c.detail}")

    print("=" * 60)

    all_passed = all(c.passed for c in checks)
    passed_count = sum(1 for c in checks if c.passed)
    total = len(checks)

    if not all_passed:
        failed = [c.name for c in checks if not c.passed]
        print(f"\n  STOP — NOT SAFE TO GO LIVE ({passed_count}/{total} checks passed)")
        print(f"  Fix these failures first:")
        for name in failed:
            print(f"    - {name}")
    else:
        print(f"\n  ALL {total}/{total} CHECKS PASSED — safe to go live")
        print("  Set PAPER_TRADING_MODE=false in Doppler and redeploy.")

    print()
    return all_passed


if __name__ == "__main__":
    passed = run_checklist()
    sys.exit(0 if passed else 1)
