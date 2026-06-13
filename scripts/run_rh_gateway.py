#!/usr/bin/env python3
"""
scripts/run_rh_gateway.py — Smoke-test / startup script for the RH Gateway.

Usage:
    python scripts/run_rh_gateway.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gateway.rh_gateway import RHGateway
from core.schemas import TradeSignal


async def main() -> None:
    gateway = RHGateway(paper_mode=True)
    print("RH Gateway ready (paper mode)")

    account = await gateway.get_account()
    print(f"Account info: {account}")

    positions = await gateway.get_positions()
    print(f"Open positions: {len(positions)}")


if __name__ == "__main__":
    asyncio.run(main())
