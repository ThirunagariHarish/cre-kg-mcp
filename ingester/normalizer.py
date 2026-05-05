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
# Taxonomy canonicalization
# ---------------------------------------------------------------------------

def taxonomy_key(value: str, kind: str) -> str:
    """
    Returns the canonical name for a taxonomy value (market, asset_class, etc.).

    If the value is unmapped, the raw lowercased value is returned and a
    warning is logged so operators can extend canonical_map.yaml.
    """
    normalized = value.strip().lower()
    result = _ALIAS_TO_CANONICAL.get(normalized)
    if result is not None:
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
    }
    label = label_map.get(kind)
    if label is None:
        log.warning("unmapped_taxonomy_kind", kind=kind, raw_tag=tag)
        return None
    return (label, canon)
