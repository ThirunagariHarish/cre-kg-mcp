"""
scripts/run_all_analysts.py — Canonical single-command entry point for all analysts.

Usage:
    # Paper mode (default — safe, no real orders)
    doppler run -- python scripts/run_all_analysts.py
    doppler run -- python scripts/run_all_analysts.py --paper

    # Live mode — PAPER_TRADING_MODE must be explicitly "false" in env
    doppler run -- python scripts/run_all_analysts.py --live

Flags:
    --paper   Force paper mode regardless of env (default if no flag given)
    --live    Enable live trading. Requires PAPER_TRADING_MODE=false in the
              environment — this is a deliberate two-step safety gate.
              Will abort with an error if the env var is not set correctly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("run_all_analysts")

_CONFIG_DIR = Path(__file__).parent.parent / "configs" / "analysts"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch all Discord analysts + MasterAnalyst + MonitorAgent + DiscordGateway",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--paper",
        action="store_true",
        default=False,
        help="Run in paper mode (default — simulates all orders, no real money)",
    )
    mode.add_argument(
        "--live",
        action="store_true",
        default=False,
        help=(
            "Run in live trading mode. "
            "Requires PAPER_TRADING_MODE=false to be set in the environment."
        ),
    )
    return parser.parse_args()


def _resolve_paper_mode(args: argparse.Namespace) -> bool:
    """
    Resolve paper/live mode from CLI flags and env vars.

    Rules:
      --paper flag  → always paper (safe)
      --live flag   → require PAPER_TRADING_MODE=false in env, else abort
      neither flag  → default to paper (safe)
    """
    if args.live:
        env_val = os.environ.get("PAPER_TRADING_MODE", "").strip().lower()
        if env_val != "false":
            logger.critical(
                "--live flag passed but PAPER_TRADING_MODE is %r (expected 'false'). "
                "Set PAPER_TRADING_MODE=false in your environment / Doppler config to go live.",
                os.environ.get("PAPER_TRADING_MODE", "(not set)"),
            )
            sys.exit(1)
        logger.warning(
            "LIVE TRADING MODE ENABLED — real orders will be sent to Robinhood!"
        )
        return False  # live
    else:
        # --paper or no flag → paper mode
        if not args.paper:
            logger.info("No --paper/--live flag given — defaulting to paper mode (safe)")
        return True  # paper


def load_config(name: str) -> dict:
    """Load an analyst config JSON by name (without .json extension)."""
    path = _CONFIG_DIR / f"{name}.json"
    return json.loads(path.read_text())


def _channel_from_env_or_config(env_var: str, config_value: str) -> str:
    """Prefer env var over config file value. Returns empty string if neither set."""
    return os.environ.get(env_var, config_value) or ""


async def run(paper_mode: bool) -> None:
    """
    Main async entry point.  Shared with run_discord_gateway for import compatibility.
    """
    from core.redis_client import init_redis, close_redis
    from analysts.discord.gateway import DiscordGateway
    from analysts.discord.vinod import VinodSPXAnalyst, VinodOtherAnalyst
    from analysts.discord.albert import AlbertAnalyst
    from analysts.discord.zabes import ZabesAnalyst
    from analysts.discord.adi import ADIAnalyst
    from analysts.discord.pilla_swings import PillaSwingsAnalyst
    from analysts.discord.everest import EverestAnalyst
    from master.master_analyst import MasterAnalyst
    from gateway.monitor_agent import MonitorAgent
    from gateway.rh_gateway import RHGateway
    from core.schemas import TradeSignal

    # ── Redis (must be first — heartbeat loops start inside analysts) ─────────
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    try:
        await init_redis(redis_url)
    except Exception as exc:
        logger.warning("Redis unavailable (%s) — heartbeats will be skipped", exc)

    token     = os.environ["DISCORD_BOT_TOKEN"]
    server_id = os.environ.get("DISCORD_SERVER_ID", "")

    # ── Shared queues ─────────────────────────────────────────────────────────
    signal_queue:  asyncio.Queue[TradeSignal] = asyncio.Queue()
    gateway_queue: asyncio.Queue[TradeSignal] = asyncio.Queue()
    sell_queues:   dict[str, asyncio.Queue[dict]] = {}

    # ── Load configs ──────────────────────────────────────────────────────────
    cfg_vinod_spx   = load_config("vinod_spx")
    cfg_vinod_other = load_config("vinod_other")
    cfg_albert      = load_config("albert")
    cfg_zabes       = load_config("zabes")
    cfg_adi         = load_config("adi")
    cfg_pilla       = load_config("pilla_swings")
    cfg_everest     = load_config("everest")

    # ── Resolve channel IDs ───────────────────────────────────────────────────
    spx_channel_id     = _channel_from_env_or_config(
        "DISCORD_VINOD_SPX_CHANNEL_ID",   cfg_vinod_spx.get("discord_channel_id", ""))
    other_channel_id   = _channel_from_env_or_config(
        "DISCORD_VINOD_OTHER_CHANNEL_ID", cfg_vinod_other.get("discord_channel_id", ""))
    albert_channel_id  = _channel_from_env_or_config(
        "DISCORD_ALBERT_CHANNEL_ID",      cfg_albert.get("discord_channel_id", ""))
    zabes_channel_id   = _channel_from_env_or_config(
        "DISCORD_ZABES_CHANNEL_ID",       cfg_zabes.get("discord_channel_id", ""))
    adi_channel_id     = _channel_from_env_or_config(
        "DISCORD_ADI_CHANNEL_ID",         cfg_adi.get("discord_channel_id", ""))
    pilla_channel_id   = _channel_from_env_or_config(
        "DISCORD_PILLA_CHANNEL_ID",       cfg_pilla.get("discord_channel_id", ""))
    everest_channel_id = _channel_from_env_or_config(
        "DISCORD_EVEREST_CHANNEL_ID",     cfg_everest.get("discord_channel_id", ""))

    # ── Build analysts ────────────────────────────────────────────────────────
    vinod_spx = VinodSPXAnalyst(
        signal_queue=signal_queue,
        channel_id=spx_channel_id,
        entry_buffer_pct=cfg_vinod_spx.get("entry_buffer_pct", 0.30),
        execution_buffer_pct=cfg_vinod_spx.get("execution_buffer_pct", 0.20),
        max_premium_usd=cfg_vinod_spx.get("max_premium_usd", 800.0),
        confidence_threshold=cfg_vinod_spx.get("confidence_threshold", 0.70),
    )
    vinod_other = VinodOtherAnalyst(
        signal_queue=signal_queue,
        channel_id=other_channel_id,
        entry_buffer_pct=cfg_vinod_other.get("entry_buffer_pct", 0.30),
        execution_buffer_pct=cfg_vinod_other.get("execution_buffer_pct", 0.20),
        max_premium_usd=cfg_vinod_other.get("max_premium_usd", 800.0),
        confidence_threshold=cfg_vinod_other.get("confidence_threshold", 0.70),
    )
    albert = AlbertAnalyst(
        signal_queue=signal_queue,
        channel_id=albert_channel_id,
        execution_buffer_pct=cfg_albert.get("execution_buffer_pct", 0.20),
        max_premium_usd=cfg_albert.get("max_premium_usd", 800.0),
        confidence_threshold=cfg_albert.get("confidence_threshold", 0.70),
    )
    zabes = ZabesAnalyst(
        signal_queue=signal_queue,
        channel_id=zabes_channel_id,
        execution_buffer_pct=cfg_zabes.get("execution_buffer_pct", 0.20),
        max_premium_usd=cfg_zabes.get("max_premium_usd", 600.0),
        confidence_threshold=cfg_zabes.get("confidence_threshold", 0.60),
    )
    adi = ADIAnalyst(
        signal_queue=signal_queue,
        channel_id=adi_channel_id,
        execution_buffer_pct=cfg_adi.get("execution_buffer_pct", 0.15),
        max_premium_usd=cfg_adi.get("max_premium_usd", 800.0),
        confidence_threshold=cfg_adi.get("confidence_threshold", 0.75),
    )
    pilla = PillaSwingsAnalyst(
        signal_queue=signal_queue,
        channel_id=pilla_channel_id,
        execution_buffer_pct=cfg_pilla.get("execution_buffer_pct", 0.20),
        max_premium_usd=cfg_pilla.get("max_premium_usd", 1000.0),
        confidence_threshold=cfg_pilla.get("confidence_threshold", 0.72),
    )
    everest = EverestAnalyst(
        signal_queue=signal_queue,
        channel_id=everest_channel_id,
        execution_buffer_pct=cfg_everest.get("execution_buffer_pct", 0.20),
        max_premium_usd=cfg_everest.get("max_premium_usd", 800.0),
        confidence_threshold=cfg_everest.get("confidence_threshold", 0.65),
    )

    analysts = [
        (spx_channel_id,     vinod_spx),
        (other_channel_id,   vinod_other),
        (albert_channel_id,  albert),
        (zabes_channel_id,   zabes),
        (adi_channel_id,     adi),
        (pilla_channel_id,   pilla),
        (everest_channel_id, everest),
    ]

    # ── Build sell queues ─────────────────────────────────────────────────────
    for channel_id, _ in analysts:
        if channel_id and "PLACEHOLDER" not in channel_id:
            sell_queues[channel_id] = asyncio.Queue()

    # ── Build gateway and register channels ───────────────────────────────────
    discord_gateway = DiscordGateway(token=token, server_id=server_id)
    for channel_id, analyst in analysts:
        if not channel_id or "PLACEHOLDER" in channel_id:
            logger.warning(
                "Analyst %s skipped — channel_id not configured",
                analyst.analyst_id,
            )
            continue
        discord_gateway.subscribe(channel_id, analyst.message_queue)
        if channel_id in sell_queues:
            discord_gateway.subscribe_sell(channel_id, sell_queues[channel_id])

    # ── Build MasterAnalyst ───────────────────────────────────────────────────
    master = MasterAnalyst(
        signal_queue=signal_queue,
        gateway_queue=gateway_queue,
        paper_mode=paper_mode,
    )

    # ── Build RH Gateway + MonitorAgent ──────────────────────────────────────
    rh_gateway = RHGateway(paper_mode=paper_mode)
    monitor = MonitorAgent(
        gateway=rh_gateway,
        sell_queues=sell_queues,
        poll_interval_seconds=30,
    )

    # ── Graceful shutdown ─────────────────────────────────────────────────────
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Shutdown signal received — stopping all components")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    async def shutdown_watcher() -> None:
        await stop_event.wait()
        await discord_gateway.close()
        await close_redis()

    configured_count = sum(
        1 for ch, _ in analysts
        if ch and "PLACEHOLDER" not in ch
    )
    logger.info(
        "Starting all analysts | paper_mode=%s | server=%s | analysts=%d/%d configured",
        paper_mode,
        server_id,
        configured_count,
        len(analysts),
    )
    for ch, a in analysts:
        status = "OK" if (ch and "PLACEHOLDER" not in ch) else "SKIP (no channel_id)"
        logger.info("  %-20s channel=%-25s %s", a.analyst_id, ch or "(empty)", status)

    await asyncio.gather(
        discord_gateway.run(),
        *(analyst.run() for _, analyst in analysts),
        master.run(),
        monitor.run(),
        shutdown_watcher(),
    )


def main() -> None:
    args = _parse_args()
    paper_mode = _resolve_paper_mode(args)
    try:
        asyncio.run(run(paper_mode=paper_mode))
    except KeyboardInterrupt:
        logger.info("Stopped by user")


if __name__ == "__main__":
    main()
