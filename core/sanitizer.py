"""
core/sanitizer.py — Discord message sanitizer.

Strips Unicode obfuscation and blocks prompt injection before any LLM call.
Ported and hardened from Legacy's trade_agent/safety/sanitizer.py.

Legacy lesson: zero-width chars (ZWSP, ZWNJ, ZWJ, LRM/RLM, bidi markup)
were used to bypass keyword filters. Strip them FIRST, before any regex.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# ─────────────────────────────────────────────
# Unicode zero-width and directional control chars to strip
# ─────────────────────────────────────────────

_ZERO_WIDTH_CHARS = re.compile(
    r"[​‌‍‎‏"   # ZWSP, ZWNJ, ZWJ, LRM, RLM
    r"‪‫‬‭‮"   # bidi embedding/override
    r"⁠⁡⁢⁣⁤"   # word joiner, invisible math operators
    r"﻿"                             # BOM / zero-width no-break space
    r"­]",                           # soft hyphen
    re.UNICODE,
)

# ─────────────────────────────────────────────
# Hard-block prompt injection patterns
# These immediately flag the message — do NOT send to LLM.
# ─────────────────────────────────────────────

_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(previous|all|above|prior)\s+(instructions?|prompts?|context)", re.I),
    re.compile(r"you\s+are\s+now\s+(a|an|acting\s+as)", re.I),
    re.compile(r"(system|assistant|user)\s*:\s*", re.I),  # role injection
    re.compile(r"<\|?(im_start|im_end|endoftext)\|?>", re.I),  # Anthropic tokens
    re.compile(r"jailbreak", re.I),
    re.compile(r"do\s+anything\s+now", re.I),
    re.compile(r"(```|~~~)\s*(buy|sell|trade|execute|place\s+order)", re.I),  # code-fence commands
    re.compile(r"forget\s+(everything|all|your\s+instructions)", re.I),
    re.compile(r"reveal\s+(your\s+)?(system\s+)?prompt", re.I),
    re.compile(r"act\s+as\s+(if\s+you\s+are|a)", re.I),
    re.compile(r"from\s+now\s+on\s+you\s+(will|must|should)", re.I),
    re.compile(r"disregard\s+(your|all|the)", re.I),
    re.compile(r"override\s+(safety|filter|instruction)", re.I),
]

# ─────────────────────────────────────────────
# Soft flags — logged but not blocked
# ─────────────────────────────────────────────

_URL_PATTERN = re.compile(r"https?://\S+", re.I)

# Max message length we'll process (longest real alert ~200 chars)
MAX_MESSAGE_BYTES = 2048


@dataclass(frozen=True)
class SanitizeResult:
    text: str           # cleaned text ready for parsing / LLM
    flagged: bool       # True = hard block, do NOT process
    flag_reason: str    # human-readable reason if flagged
    had_zero_width: bool  # True if zero-width chars were stripped
    had_urls: bool      # True if URLs were present (logged, not blocked)
    truncated: bool     # True if message was too long and was truncated


def sanitize(raw: str) -> SanitizeResult:
    """
    Sanitize a Discord message before parsing or LLM forwarding.

    Steps:
      1. Length cap (hard block if > 2048 bytes raw)
      2. Strip zero-width / bidi control chars
      3. Unicode normalize (NFC)
      4. Check prompt injection patterns (hard block)
      5. Detect URLs (soft log)
      6. Truncate to MAX_MESSAGE_BYTES if needed
    """
    # Step 1 — length cap on raw bytes
    raw_bytes = len(raw.encode("utf-8"))
    truncated = False
    if raw_bytes > MAX_MESSAGE_BYTES:
        # Truncate to MAX_MESSAGE_BYTES bytes, decode safely
        raw = raw.encode("utf-8")[:MAX_MESSAGE_BYTES].decode("utf-8", errors="ignore")
        truncated = True

    # Step 2 — strip zero-width chars
    cleaned, n_subs = _ZERO_WIDTH_CHARS.subn("", raw)
    had_zero_width = n_subs > 0

    # Step 3 — Unicode normalize
    cleaned = unicodedata.normalize("NFC", cleaned)

    # Step 4 — prompt injection hard-block
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(cleaned):
            return SanitizeResult(
                text="",
                flagged=True,
                flag_reason=f"Prompt injection pattern matched: {pattern.pattern!r}",
                had_zero_width=had_zero_width,
                had_urls=bool(_URL_PATTERN.search(cleaned)),
                truncated=truncated,
            )

    # Step 5 — URL soft detection
    had_urls = bool(_URL_PATTERN.search(cleaned))

    return SanitizeResult(
        text=cleaned.strip(),
        flagged=False,
        flag_reason="",
        had_zero_width=had_zero_width,
        had_urls=had_urls,
        truncated=truncated,
    )
