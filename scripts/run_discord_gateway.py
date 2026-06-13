"""
scripts/run_discord_gateway.py — Entry point for the Discord Gateway process.

Starts the Discord WebSocket, wires Vinod SPX and Vinod Other analysts,
and feeds both into the Master Analyst signal queue.

Run via:
    doppler run -- python scripts/run_discord_gateway.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from analysts.discord.gateway import DiscordGateway
from analysts.discord.vinod import VinodSPXAnalyst, VinodOtherAnalyst
from core.schemas import TradeSignal

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("discord_gateway_runner")


async def main() -> None:
    token = os.environ["DISCORD_BOT_TOKEN"]
    server_id = os.environ["DISCORD_SERVER_ID"]
    spx_channel_id = os.environ["DISCORD_VINOD_SPX_CHANNEL_ID"]
    other_channel_id = os.environ["DISCORD_VINOD_OTHER_CHANNEL_ID"]

    # Shared signal queue → Master Analyst (placeholder: just logs for now)
    signal_queue: asyncio.Queue[TradeSignal] = asyncio.Queue()

    # Build analysts
    vinod_spx = VinodSPXAnalyst(
        signal_queue=signal_queue,
        channel_id=spx_channel_id,
    )
    vinod_other = VinodOtherAnalyst(
        signal_queue=signal_queue,
        channel_id=other_channel_id,
    )

    # Build gateway and wire channels
    gateway = DiscordGateway(token=token, server_id=server_id)
    gateway.subscribe(spx_channel_id, vinod_spx.message_queue)
    gateway.subscribe(other_channel_id, vinod_other.message_queue)

    # Signal consumer (placeholder until Master Analyst is built)
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

    logger.info(
        "Starting Discord gateway | SPX channel=%s | Other channel=%s",
        spx_channel_id, other_channel_id,
    )

    await asyncio.gather(
        gateway.run(),
        vinod_spx.run(),
        vinod_other.run(),
        consume_signals(),
    )


if __name__ == "__main__":
    asyncio.run(main())
