"""
scripts/run_discord_gateway.py — Entry point for the Discord Gateway process.

Starts the Discord WebSocket, wires ALL analysts, and feeds them into the
Master Analyst signal queue.

Analysts wired:
  - Vinod SPX      (channel: DISCORD_VINOD_SPX_CHANNEL_ID   or config)
  - Vinod Other    (channel: DISCORD_VINOD_OTHER_CHANNEL_ID  or config)
  - Albert         (channel: DISCORD_ALBERT_CHANNEL_ID       or config)
  - Zabes          (channel: DISCORD_ZABES_CHANNEL_ID        or config)
  - ADI            (channel: DISCORD_ADI_CHANNEL_ID          or config)
  - Pilla          (channel: DISCORD_PILLA_CHANNEL_ID        or config)
  - Everest        (channel: DISCORD_EVEREST_CHANNEL_ID      or config)

Run via:
    doppler run -- python scripts/run_discord_gateway.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from analysts.discord.gateway import DiscordGateway
from analysts.discord.vinod import VinodSPXAnalyst, VinodOtherAnalyst
from analysts.discord.albert import AlbertAnalyst
from analysts.discord.zabes import ZabesAnalyst
from analysts.discord.adi import ADIAnalyst
from analysts.discord.pilla_swings import PillaSwingsAnalyst
from analysts.discord.everest import EverestAnalyst
from core.schemas import TradeSignal

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("discord_gateway_runner")

_CONFIG_DIR = Path(__file__).parent.parent / "configs" / "analysts"


def load_config(name: str) -> dict:
    """Load an analyst config JSON by name (without .json extension)."""
    path = _CONFIG_DIR / f"{name}.json"
    return json.loads(path.read_text())


def _channel_from_env_or_config(env_var: str, config_key: str) -> str:
    """
    Resolve a Discord channel ID.

    Priority:
      1. Environment variable (env_var)
      2. Value in config dict (config_key already loaded)
      3. Empty string — analyst will be skipped at subscribe time
    """
    return os.environ.get(env_var, config_key) or ""


async def main() -> None:
    token = os.environ["DISCORD_BOT_TOKEN"]
    server_id = os.environ.get("DISCORD_SERVER_ID", "")

    # ── Shared signal queue → MasterAnalyst ──────────────────────────────────
    signal_queue: asyncio.Queue[TradeSignal] = asyncio.Queue()

    # ── Sell queues keyed by channel_id → MonitorAgent ───────────────────────
    # Each channel that can emit sell signals needs its own queue so the
    # MonitorAgent can drain sell messages independently from buy parsing.
    sell_queues: dict[str, asyncio.Queue[dict]] = {}

    # ── Load configs ─────────────────────────────────────────────────────────
    cfg_vinod_spx   = load_config("vinod_spx")
    cfg_vinod_other = load_config("vinod_other")
    cfg_albert      = load_config("albert")
    cfg_zabes       = load_config("zabes")
    cfg_adi         = load_config("adi")
    cfg_pilla       = load_config("pilla_swings")
    cfg_everest     = load_config("everest")

    # ── Resolve channel IDs (env overrides config) ────────────────────────────
    spx_channel_id   = _channel_from_env_or_config(
        "DISCORD_VINOD_SPX_CHANNEL_ID",   cfg_vinod_spx.get("discord_channel_id", ""))
    other_channel_id = _channel_from_env_or_config(
        "DISCORD_VINOD_OTHER_CHANNEL_ID", cfg_vinod_other.get("discord_channel_id", ""))
    albert_channel_id = _channel_from_env_or_config(
        "DISCORD_ALBERT_CHANNEL_ID",      cfg_albert.get("discord_channel_id", ""))
    zabes_channel_id = _channel_from_env_or_config(
        "DISCORD_ZABES_CHANNEL_ID",       cfg_zabes.get("discord_channel_id", ""))
    adi_channel_id   = _channel_from_env_or_config(
        "DISCORD_ADI_CHANNEL_ID",         cfg_adi.get("discord_channel_id", ""))
    pilla_channel_id = _channel_from_env_or_config(
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

    # All analysts indexed by channel_id for easy gateway registration.
    # Analysts with placeholder/empty channel IDs are still built but not
    # subscribed (safe no-op — they will never receive messages).
    analysts = [
        (spx_channel_id,     vinod_spx),
        (other_channel_id,   vinod_other),
        (albert_channel_id,  albert),
        (zabes_channel_id,   zabes),
        (adi_channel_id,     adi),
        (pilla_channel_id,   pilla),
        (everest_channel_id, everest),
    ]

    # ── Build sell queues for all channels that have analysts ─────────────────
    for channel_id, _ in analysts:
        if channel_id and "PLACEHOLDER" not in channel_id:
            sell_queues[channel_id] = asyncio.Queue()

    # ── Build gateway and register channels ───────────────────────────────────
    gateway = DiscordGateway(token=token, server_id=server_id)
    for channel_id, analyst in analysts:
        if not channel_id or "PLACEHOLDER" in channel_id:
            logger.warning(
                "Analyst %s skipped — channel_id not configured (set env var or config)",
                analyst.analyst_id,
            )
            continue
        gateway.subscribe(channel_id, analyst.message_queue)
        if channel_id in sell_queues:
            gateway.subscribe_sell(channel_id, sell_queues[channel_id])

    # ── Signal consumer (placeholder until MasterAnalyst is wired in) ─────────
    async def consume_signals() -> None:
        while True:
            signal = await signal_queue.get()
            logger.info(
                "SIGNAL: analyst=%s symbol=%s direction=%s strike=%.0f expiry=%s price=%.2f conf=%.2f",
                signal.analyst_id,
                signal.symbol,
                signal.direction,
                signal.strike,
                signal.expiry,
                signal.signal_price,
                signal.confidence,
            )

    # ── Graceful shutdown ─────────────────────────────────────────────────────
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Shutdown signal received — stopping gateway")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    async def shutdown_watcher() -> None:
        await stop_event.wait()
        await gateway.close()

    configured_count = sum(
        1 for ch, _ in analysts
        if ch and "PLACEHOLDER" not in ch
    )
    logger.info(
        "Starting Discord gateway | server=%s | analysts=%d/%d configured",
        server_id,
        configured_count,
        len(analysts),
    )
    for ch, a in analysts:
        status = "OK" if (ch and "PLACEHOLDER" not in ch) else "SKIP (no channel_id)"
        logger.info("  %-20s channel=%-25s %s", a.analyst_id, ch or "(empty)", status)

    await asyncio.gather(
        gateway.run(),
        *(analyst.run() for _, analyst in analysts),
        consume_signals(),
        shutdown_watcher(),
    )


if __name__ == "__main__":
    asyncio.run(main())
