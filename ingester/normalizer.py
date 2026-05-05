"""
Merge-key derivation and taxonomy canonicalization for CRE entities.

All functions are pure (no I/O) and deterministic so they can be unit-tested
without touching Snowflake or Neo4j.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional

import structlog
import yaml

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Canonical map — loaded once at module import
# ---------------------------------------------------------------------------
_MAP_PATH = Path(__file__).parent / "canonical_map.yaml"

with open(_MAP_PATH) as _f:
    _RAW_MAP: dict = yaml.safe_load(_f)

# Build inverted lookup: alias (lowercase) -> (kind, canonical_name)
_ALIAS_TO_CANONICAL: dict[str, tuple[str, str]] = {}
for _kind, _entries in _RAW_MAP.items():
    for _canon, _aliases in _entries.items():
        # The canonical key itself is also a valid alias
        _ALIAS_TO_CANONICAL[_canon.strip().lower()] = (_kind, _canon)
        for _alias in _aliases:
            _ALIAS_TO_CANONICAL[_alias.strip().lower()] = (_kind, _canon)


# ---------------------------------------------------------------------------
# Merge-key functions (per data-model.md §4.1)
# ---------------------------------------------------------------------------

def broker_key(row: dict) -> str:
    """
    Derives the stable merge key for a Broker node.

    Priority: email (if present and non-blank) → name+firm tuple.
    Handles both CRE_BROKERS (FULL_NAME, FIRM_NAME) and CRE_LEASE_COMPS
    (TENANT_BROKER_FIRM columns).
    """
    email = (row.get("EMAIL") or row.get("email") or "").strip().lower()
    if email:
        return f"email::{email}"
    # CRE_BROKERS uses FULL_NAME; fallback to BROKER_NAME for legacy callers
    name = (
        row.get("FULL_NAME")
        or row.get("BROKER_NAME")
        or row.get("broker_name")
        or ""
    ).strip().lower()
    firm = (
        row.get("FIRM_NAME")
        or row.get("FIRM")
        or row.get("firm")
        or ""
    ).strip().lower()
    return f"name::{name}::firm::{firm}"


def property_key(row: dict) -> str:
    """
    Derives the stable merge key for a Property node.

    Priority: property_id (if present) → normalized address + zip.
    Handles CRE_PROPERTIES (PROPERTY_ID, ZIP_CODE) and CRE_LEASE_COMPS
    (PROPERTY_ADDRESS, ZIP_CODE).
    """
    pid = (row.get("PROPERTY_ID") or row.get("property_id") or "").strip()
    if pid:
        return f"id::{pid}"
    addr = (
        row.get("PROPERTY_ADDRESS")
        or row.get("ADDRESS")
        or row.get("address")
        or ""
    ).strip().lower()
    # Collapse whitespace
    addr = re.sub(r"\s+", " ", addr)
    # Strip suite/unit qualifiers (handles "Suite 200", "Ste B", "Unit 14", "# 14", "#14")
    addr = re.sub(r"\b(suite|ste|unit)\s*\S+", "", addr)
    addr = re.sub(r"\s*#\s*\S+", "", addr).strip()
    zip_code = (
        row.get("ZIP_CODE")
        or row.get("ZIP")
        or row.get("zip")
        or ""
    ).strip()
    return f"addr::{addr}::zip::{zip_code}"


def tenant_key(row: dict) -> str:
    name = (row.get("TENANT_NAME") or row.get("tenant_name") or "").strip().lower()
    return f"name::{name}"


def landlord_key(row: dict) -> str:
    name = (
        row.get("OWNER_NAME")         # CRE_PROPERTIES
        or row.get("LANDLORD_NAME")
        or row.get("landlord_name")
        or row.get("OWNER")
        or row.get("owner")
        or ""
    ).strip().lower()
    return f"name::{name}"


def lease_key(row: dict) -> str:
    # CRE_LEASE_COMPS uses COMP_ID as the primary key
    lid = (
        row.get("COMP_ID")
        or row.get("LEASE_ID")
        or row.get("lease_id")
        or ""
    ).strip()
    if lid:
        return f"id::{lid}"
    prop = property_key(row)
    tenant = tenant_key(row)
    date_val = str(
        row.get("SIGNED_DATE")
        or row.get("EXECUTION_DATE")
        or row.get("execution_date")
        or ""
    )
    raw = f"{prop}|{tenant}|{date_val}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"hash::{digest}"


def client_key(row: dict) -> str:
    # CRE_PURSUITS uses ORGANIZATION or CLIENT_NAME
    # CRE_SPOC uses ACCOUNT_NAME
    name = (
        row.get("ACCOUNT_NAME")      # CRE_SPOC
        or row.get("ORGANIZATION")   # CRE_PURSUITS
        or row.get("CLIENT_NAME")
        or row.get("client_name")
        or ""
    ).strip().lower()
    return f"name::{name}"


def client_display_name(row: dict) -> str:
    """
    B3: Returns the best available display name for a Client node.

    Applies the same fallback chain as client_key() so the node's `name`
    property is never empty when the key is non-empty.

    Fallback order: ACCOUNT_NAME (CRE_SPOC) → ORGANIZATION (CRE_PURSUITS) → CLIENT_NAME.
    """
    return (
        row.get("ACCOUNT_NAME")
        or row.get("ORGANIZATION")
        or row.get("CLIENT_NAME")
        or row.get("client_name")
        or ""
    ).strip()


def broker_key_from_pursuit(row: dict) -> str:
    """
    Builds a broker merge key from a CRE_PURSUITS row.
    CRE_PURSUITS uses SALES_MANAGEMENT_LEAD for broker name.
    """
    email = (row.get("BROKER_EMAIL") or row.get("broker_email") or "").strip().lower()
    if email:
        return f"email::{email}"
    name = (
        row.get("SALES_MANAGEMENT_LEAD")  # CRE_PURSUITS primary broker field
        or row.get("ASSIGNED_BROKER")
        or row.get("assigned_broker")
        or ""
    ).strip().lower()
    firm = (row.get("BROKER_FIRM") or row.get("broker_firm") or "").strip().lower()
    return f"name::{name}::firm::{firm}"


def broker_key_from_spoc(row: dict) -> str:
    """
    Builds a broker merge key from a CRE_SPOC row.
    CRE_SPOC uses SPOC_EMAIL and SPOC_EMPLOYEE_NAME.
    """
    email = (
        row.get("SPOC_EMAIL")
        or row.get("BROKER_EMAIL")
        or row.get("broker_email")
        or ""
    ).strip().lower()
    if email:
        return f"email::{email}"
    name = (
        row.get("SPOC_EMPLOYEE_NAME")
        or row.get("BROKER_NAME")
        or row.get("broker_name")
        or ""
    ).strip().lower()
    firm = (row.get("FIRM") or row.get("firm") or "").strip().lower()
    return f"name::{name}::firm::{firm}"


# ---------------------------------------------------------------------------
# BUG-005: Email-domain to firm name mapping
# Used when broker row has no FIRM_NAME column.
# ---------------------------------------------------------------------------
_EMAIL_DOMAIN_TO_FIRM: dict[str, str] = {
    "cbre.com": "CBRE",
    "jll.com": "JLL",
    "cushman&wakefield.com": "Cushman & Wakefield",
    "cushmanwakefield.com": "Cushman & Wakefield",
    "savills.com": "Savills",
    "colliers.com": "Colliers",
    "eastdilsecured.com": "Eastdil Secured",
    "ngkf.com": "Newmark",
    "nmrk.com": "Newmark",
    "newmark.com": "Newmark",
    "knightfrank.com": "Knight Frank",
    "lee-associates.com": "Lee & Associates",
    "marcusmillichap.com": "Marcus & Millichap",
    "cbiz.com": "CBIZ",
}


def firm_from_email(email: str) -> str | None:
    """
    BUG-005 FIX: Derive firm name from email domain when FIRM_NAME is absent.
    Returns None if the domain is not in the known map.
    """
    if not email:
        return None
    parts = email.strip().lower().split("@")
    if len(parts) != 2:
        return None
    domain = parts[1]
    return _EMAIL_DOMAIN_TO_FIRM.get(domain)


# ---------------------------------------------------------------------------
# Taxonomy canonicalization
# ---------------------------------------------------------------------------

def _strip_submarket_prefix(value: str) -> list[str]:
    """
    BUG-003 FIX: For market-kind lookups, generate candidate strings by
    stripping leading submarket/neighborhood tokens from compound names.

    "back bay boston"  → tries "back bay boston", "bay boston", "boston"
    "downtown manhattan" → tries "downtown manhattan", "manhattan"
    "soma san francisco" → tries "soma san francisco", "san francisco"

    Returns candidates in order: full value first, then progressively shorter
    suffix slices (dropping one token at a time from the left).
    """
    tokens = value.strip().lower().split()
    candidates = []
    # Start with full value, then drop one leading token at a time
    for i in range(len(tokens)):
        candidates.append(" ".join(tokens[i:]))
    return candidates


def taxonomy_key(value: str, kind: str) -> str:
    """
    Returns the canonical name for a taxonomy value (market, asset_class, etc.).

    If the value is unmapped, the raw lowercased value is returned and a
    warning is logged so operators can extend canonical_map.yaml.

    BUG-003 FIX: For markets, if the full value is unmapped and contains 2+
    tokens, progressively strip leading tokens to find a canonical match.
    This maps submarket-prefixed names like "back bay boston" → "boston" and
    "downtown manhattan" → "new york" without editing canonical_map.yaml.
    """
    normalized = value.strip().lower()
    result = _ALIAS_TO_CANONICAL.get(normalized)
    if result is not None:
        return result[1]

    # BUG-003: prefix-stripping fallback for market names with 2+ tokens
    if kind == "markets" and " " in normalized:
        for candidate in _strip_submarket_prefix(normalized)[1:]:  # skip full value (already tried)
            result = _ALIAS_TO_CANONICAL.get(candidate)
            if result is not None and result[0] == "markets":
                log.info(
                    "market_prefix_stripped",
                    raw_value=value,
                    candidate=candidate,
                    canonical=result[1],
                )
                return result[1]

    log.warning("unmapped_taxonomy_value", kind=kind, raw_value=value)
    return normalized


def canonical_resolver(tag: str) -> Optional[tuple[str, str]]:
    """
    Resolves a free-form insight tag to a (node_label, canonical_name) tuple.

    Used by the streaming insight consumer (Phase 2). Returns None when the
    tag cannot be resolved to any known taxonomy entry.

    Special prefixes:
      "tenant:<name>"   → ("Tenant", tenant_key_from_name)
      "property:<id>"   → ("Property", "id::<id>")
    Otherwise matches against markets, asset_classes, service_lines.
    """
    tag = tag.strip()
    lower = tag.lower()

    if lower.startswith("tenant:"):
        name = tag[len("tenant:"):].strip().lower()
        return ("Tenant", f"name::{name}")
    if lower.startswith("property:"):
        pid = tag[len("property:"):].strip()
        return ("Property", f"id::{pid}")

    result = _ALIAS_TO_CANONICAL.get(lower)
    if result is None:
        log.warning("unmapped_insight_tag", raw_tag=tag)
        return None

    kind, canon = result
    label_map = {
        "markets": "Market",
        "asset_classes": "AssetClass",
        "service_lines": "ServiceLine",
        # M-P3-7 / M-P2-4 FIX: submarkets resolve to Market via their parent market alias.
        # A submarket tag like "DFW North - Urban" is an alias of a canonical submarket
        # (e.g. "dfw-north") which is itself an alias listed under the "dallas-fort worth"
        # market entry in canonical_map.yaml. The canonical_map has "dfw north - urban" as
        # an alias under markets.dallas-fort worth AND as a submarket alias — markets takes
        # priority in the alias lookup since markets is defined first in canonical_map.yaml.
        # However if the alias was captured only under submarkets, we map the submarket to
        # the Market label so callers get a resolvable market back.
        "submarkets": "Market",
    }
    label = label_map.get(kind)
    if label is None:
        log.warning("unmapped_taxonomy_kind", kind=kind, raw_tag=tag)
        return None

    # For submarkets: the canonical submarket name (e.g. "dfw-north") is not a Market name.
    # We need to return the parent market name. Search markets aliases for any that include
    # the canonical submarket name as an alias, or look up a fixed mapping.
    if kind == "submarkets":
        # Find the market that has this submarket's canonical name as one of its aliases,
        # OR whose markets entry covers it. We do a reverse-lookup: find any market alias
        # that contains the submarket canonical or any of the submarket's own aliases.
        # Simpler approach: re-scan _RAW_MAP["markets"] for the submarket's aliases.
        submarket_aliases_raw: list[str] = []
        if "submarkets" in _RAW_MAP and canon in _RAW_MAP["submarkets"]:
            submarket_aliases_raw = _RAW_MAP["submarkets"][canon] or []
        # Include the canonical submarket name itself
        candidates = [canon.strip().lower()] + [a.strip().lower() for a in submarket_aliases_raw]

        # Search markets for a match on any candidate alias
        for mkt_canon, mkt_aliases in (_RAW_MAP.get("markets") or {}).items():
            mkt_all = [mkt_canon.strip().lower()] + [a.strip().lower() for a in (mkt_aliases or [])]
            for c in candidates:
                if c in mkt_all:
                    return ("Market", mkt_canon)

        # No parent market found — still return Market with submarket canonical name
        log.warning("submarket_parent_market_not_found", submarket=canon, raw_tag=tag)
        return ("Market", canon)

    return (label, canon)
