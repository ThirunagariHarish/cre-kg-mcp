"""
Shared read-only Neo4j session factory for the MCP server.

The MCP server is read-only; all writes are done by the ingester process.
A single Driver is kept alive for the MCP process lifetime.
"""

from __future__ import annotations

import os
from typing import Optional

import structlog
from dotenv import load_dotenv
from neo4j import GraphDatabase, Driver

load_dotenv()

log = structlog.get_logger()

_driver: Optional[Driver] = None


def get_driver() -> Driver:
    global _driver
    if _driver is None:
        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "hackathon_local_only")
        _driver = GraphDatabase.driver(uri, auth=(user, password))
        log.info("neo4j_driver_created", uri=uri)
    return _driver


def close_driver() -> None:
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
