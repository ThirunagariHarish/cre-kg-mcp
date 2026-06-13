"""
scripts/run_backtest.py — Replay saved Discord messages through a named analyst's
parsers and print a performance report.

Usage:
    python scripts/run_backtest.py
    python scripts/run_backtest.py --analyst vinod_spx
    python scripts/run_backtest.py --analyst adi --messages-dir shared/discord_samples/
    python scripts/run_backtest.py --analyst zabes --output shared/state/backtest_zabes.json

Supported analyst ids: vinod_spx, vinod_other, adi, zabes

Message files:
  Each file in <messages-dir> must be one of:
    - JSONL  (.jsonl) — one raw Discord REST API object per line
    - JSON   (.json)  — a list of raw Discord REST API objects, OR a single object

  Raw Discord objects are normalised to the parser payload shape using the same
  logic as DiscordGateway._raw_to_payload (keys: message_id, channel_id,
  timestamp, author_id, author_name, author_global_name, is_bot, content, embeds).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path when run as a script
_HERE = Path(__file__).resolve().parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from backtesting.engine import BacktestEngine
from backtesting.report import print_report, save_report
from core.sanitizer import sanitize

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


# ---------------------------------------------------------------------------
# Discord raw → normalized payload
# ---------------------------------------------------------------------------

def _raw_to_payload(raw: dict) -> dict:
    """Mirror of DiscordGateway._raw_to_payload — no discord.py dependency."""
    author = raw.get("author", {})
    content_raw = raw.get("content", "")
    try:
        clean_content = sanitize(content_raw).text
    except Exception:
        clean_content = content_raw
    return {
        "message_id": raw.get("id", raw.get("message_id", "")),
        "channel_id": raw.get("channel_id", ""),
        "timestamp": raw.get("timestamp", ""),
        "author_id": author.get("id", raw.get("author_id", "")),
        "author_name": (
            author.get("global_name") or author.get("username") or raw.get("author_name", "")
        ),
        "author_global_name": (
            author.get("global_name") or author.get("username") or raw.get("author_global_name", "")
        ),
        "is_bot": author.get("bot", raw.get("is_bot", False)),
        "content_raw": content_raw,
        "content": clean_content,
        "embeds": raw.get("embeds", []),
    }


# ---------------------------------------------------------------------------
# Message loading
# ---------------------------------------------------------------------------

def load_messages(messages_dir: str) -> list[dict]:
    """
    Load all .jsonl and .json files from *messages_dir* and return a flat list
    of normalised message dicts sorted oldest-first by timestamp.
    """
    dir_path = Path(messages_dir)
    if not dir_path.is_dir():
        print(f"Warning: messages directory '{messages_dir}' does not exist — no messages loaded.")
        return []

    raw_messages: list[dict] = []

    for file_path in sorted(dir_path.iterdir()):
        if file_path.suffix == ".jsonl":
            with open(file_path) as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            raw_messages.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass

        elif file_path.suffix == ".json":
            with open(file_path) as fh:
                try:
                    data = json.load(fh)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, list):
                    raw_messages.extend(data)
                elif isinstance(data, dict):
                    raw_messages.append(data)

    # Normalize + sort by timestamp ascending (oldest first)
    normalized = [_raw_to_payload(m) for m in raw_messages]
    normalized.sort(key=lambda m: m.get("timestamp", ""))
    return normalized


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest an analyst against saved Discord messages.")
    parser.add_argument(
        "--analyst",
        default="vinod_spx",
        choices=["vinod_spx", "vinod_other", "adi", "zabes"],
        help="Analyst to backtest (default: vinod_spx)",
    )
    parser.add_argument(
        "--messages-dir",
        default="shared/discord_samples/",
        help="Directory containing .jsonl / .json message files (default: shared/discord_samples/)",
    )
    parser.add_argument(
        "--output",
        default="shared/state/backtest_report.json",
        help="Output JSON report path (default: shared/state/backtest_report.json)",
    )
    parser.add_argument(
        "--hard-stop",
        type=float,
        default=-0.50,
        help="Hard stop P&L threshold as a fraction, e.g. -0.50 (default: -0.50)",
    )
    parser.add_argument(
        "--take-profit",
        type=float,
        default=1.00,
        help="Take-profit P&L threshold as a fraction, e.g. 1.00 (default: 1.00)",
    )
    args = parser.parse_args()

    messages = load_messages(args.messages_dir)
    print(f"Loaded {len(messages)} messages from '{args.messages_dir}'")

    engine = BacktestEngine()
    result = await engine.run(
        analyst_id=args.analyst,
        messages=messages,
        hard_stop=args.hard_stop,
        take_profit=args.take_profit,
    )

    print_report(result)
    save_report(result, args.output)


if __name__ == "__main__":
    asyncio.run(main())
