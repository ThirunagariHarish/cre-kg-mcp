"""
scripts/scrape_discord_messages.py

Pulls raw Discord messages from a server to understand analyst message patterns.
Uses Discord REST API directly — no bot gateway needed, just the bot token.

Usage:
  doppler run -- python scripts/scrape_discord_messages.py              # list all channels
  doppler run -- python scripts/scrape_discord_messages.py --channel <ID> --limit 100
  doppler run -- python scripts/scrape_discord_messages.py --channel <ID> --limit 200 --save

Output:
  - Prints raw messages to stdout
  - With --save: writes to shared/discord_samples/<channel_id>.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE_URL = "https://discord.com/api/v10"


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bot {token}", "Content-Type": "application/json"}


def get_guild_channels(token: str, server_id: str) -> list[dict]:
    resp = httpx.get(f"{BASE_URL}/guilds/{server_id}/channels", headers=headers(token), timeout=15)
    resp.raise_for_status()
    channels = resp.json()
    # text channels only (type 0)
    return [c for c in channels if c.get("type") == 0]


def fetch_messages(token: str, channel_id: str, limit: int = 100) -> list[dict]:
    """
    Fetch up to `limit` messages from a channel using Discord's pagination.
    Discord allows max 100 per request, so we paginate with before= param.
    """
    all_msgs: list[dict] = []
    before: str | None = None

    while len(all_msgs) < limit:
        batch_size = min(100, limit - len(all_msgs))
        params: dict[str, str | int] = {"limit": batch_size}
        if before:
            params["before"] = before

        resp = httpx.get(
            f"{BASE_URL}/channels/{channel_id}/messages",
            headers=headers(token),
            params=params,
            timeout=15,
        )

        if resp.status_code == 403:
            print(f"  ⚠️  No permission to read channel {channel_id}")
            break
        if resp.status_code == 429:
            retry_after = float(resp.json().get("retry_after", 1.0))
            print(f"  Rate limited — sleeping {retry_after:.1f}s")
            time.sleep(retry_after)
            continue

        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break

        all_msgs.extend(batch)
        before = batch[-1]["id"]

        # Respect rate limits
        remaining = int(resp.headers.get("X-RateLimit-Remaining", 1))
        if remaining == 0:
            reset_after = float(resp.headers.get("X-RateLimit-Reset-After", 0.5))
            time.sleep(reset_after + 0.05)
        else:
            time.sleep(0.05)

    return all_msgs


def format_message(msg: dict) -> str:
    """Human-readable single-line representation of a Discord message."""
    author = msg.get("author", {})
    name = author.get("global_name") or author.get("username", "unknown")
    bot_flag = " [BOT]" if author.get("bot") else ""
    ts = msg.get("timestamp", "")[:19].replace("T", " ")
    content = msg.get("content", "").replace("\n", " ↵ ")
    embeds = f" [+{len(msg['embeds'])} embeds]" if msg.get("embeds") else ""
    attachments = f" [+{len(msg['attachments'])} files]" if msg.get("attachments") else ""
    return f"[{ts}] {name}{bot_flag}: {content}{embeds}{attachments}"


def analyze_patterns(messages: list[dict]) -> None:
    """Print pattern analysis — what sell/buy keywords appear, message structure."""
    print("\n" + "═" * 60)
    print("PATTERN ANALYSIS")
    print("═" * 60)

    buy_keywords = ["buy", "entry", "enter", "call", "put", "spx", "spy", "0dte",
                    "strike", "exp", "contract", "play", "position", "filled", "in "]
    sell_keywords = ["sell", "out", "sold", "exit", "close", "profit", "stop",
                     "lock", "scalp", "partial", "half", "trim", "cover"]

    buy_msgs = []
    sell_msgs = []
    other_msgs = []

    for msg in messages:
        content = msg.get("content", "").lower()
        if not content:
            continue
        if any(k in content for k in sell_keywords):
            sell_msgs.append(msg)
        elif any(k in content for k in buy_keywords):
            buy_msgs.append(msg)
        else:
            other_msgs.append(msg)

    print(f"\n📈 LIKELY BUY/ENTRY signals ({len(buy_msgs)} messages):")
    for m in buy_msgs[:20]:
        print(f"  {format_message(m)}")

    print(f"\n📉 LIKELY SELL/EXIT signals ({len(sell_msgs)} messages):")
    for m in sell_msgs[:20]:
        print(f"  {format_message(m)}")

    print(f"\n📊 OTHER messages ({len(other_msgs)} total, showing 10):")
    for m in other_msgs[:10]:
        print(f"  {format_message(m)}")

    # Authors breakdown
    from collections import Counter
    authors = Counter(
        (m.get("author", {}).get("global_name") or m.get("author", {}).get("username", "?"))
        for m in messages
    )
    print("\n👤 TOP AUTHORS:")
    for author, count in authors.most_common(10):
        print(f"  {author}: {count} messages")


def save_messages(messages: list[dict], channel_id: str) -> Path:
    out_dir = Path("shared/discord_samples")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{channel_id}.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Discord messages for pattern analysis")
    parser.add_argument("--channel", help="Channel ID to scrape (omit to list channels)")
    parser.add_argument("--limit", type=int, default=100, help="Max messages to fetch (default 100)")
    parser.add_argument("--save", action="store_true", help="Save raw JSONL to shared/discord_samples/")
    parser.add_argument("--raw", action="store_true", help="Print all messages raw (no analysis)")
    args = parser.parse_args()

    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    server_id = os.environ.get("DISCORD_SERVER_ID", "")

    if not token:
        print("ERROR: DISCORD_BOT_TOKEN not set. Run via: doppler run -- python scripts/scrape_discord_messages.py")
        sys.exit(1)
    if not server_id:
        print("ERROR: DISCORD_SERVER_ID not set.")
        sys.exit(1)

    print(f"🤖 Connected | Server: {server_id}")

    # ─── List channels mode ───────────────────────────────────────────
    if not args.channel:
        print("\nFetching channel list...")
        try:
            channels = get_guild_channels(token, server_id)
        except httpx.HTTPStatusError as e:
            print(f"ERROR fetching channels: {e.response.status_code} {e.response.text}")
            sys.exit(1)

        channels.sort(key=lambda c: (c.get("parent_id") or "", c.get("position", 0)))
        print(f"\n{'ID':<22} {'NAME':<40} CATEGORY")
        print("─" * 80)
        for ch in channels:
            print(f"{ch['id']:<22} #{ch['name']:<39} {ch.get('parent_id', '')}")

        print(f"\n✅ {len(channels)} text channels found.")
        print("\nRe-run with --channel <ID> to scrape a specific channel:")
        print("  doppler run -- python scripts/scrape_discord_messages.py --channel <ID> --limit 200")
        return

    # ─── Scrape specific channel ──────────────────────────────────────
    print(f"\nFetching up to {args.limit} messages from channel {args.channel}...")
    try:
        messages = fetch_messages(token, args.channel, limit=args.limit)
    except httpx.HTTPStatusError as e:
        print(f"ERROR: {e.response.status_code} — {e.response.text}")
        sys.exit(1)

    print(f"✅ Fetched {len(messages)} messages\n")

    if args.raw:
        for msg in reversed(messages):
            print(format_message(msg))
    else:
        # Print all messages chronologically
        print("─" * 80)
        print("ALL MESSAGES (oldest → newest):")
        print("─" * 80)
        for msg in reversed(messages):
            print(format_message(msg))

        analyze_patterns(messages)

    if args.save:
        path = save_messages(messages, args.channel)
        print(f"\n💾 Saved raw JSONL → {path}")


if __name__ == "__main__":
    main()
