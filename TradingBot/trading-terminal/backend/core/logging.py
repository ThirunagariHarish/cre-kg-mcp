"""
Structured JSON logging setup for production observability.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from typing import Any

try:
    import structlog  # type: ignore
    HAS_STRUCTLOG = True
except ImportError:
    HAS_STRUCTLOG = False


def configure_logging(
    log_level: str = "INFO",
    json_logs: bool = True,
    service_name: str = "trading-terminal",
) -> None:
    """
    Configure application logging.
    Uses structlog if available for JSON structured logs,
    falls back to standard logging with a sensible format.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    if HAS_STRUCTLOG and json_logs:
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.stdlib.add_log_level,
                structlog.stdlib.add_logger_name,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.BoundLogger,
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
        )
        logging.basicConfig(
            format="%(message)s",
            stream=sys.stdout,
            level=level,
        )
    else:
        fmt = (
            "%(asctime)s [%(levelname)s] %(name)s "
            f"service={service_name} %(message)s"
        )
        logging.basicConfig(
            format=fmt,
            datefmt="%Y-%m-%dT%H:%M:%SZ",
            stream=sys.stdout,
            level=level,
        )

    # Silence noisy libraries
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("confluent_kafka").setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Logging configured: level=%s json=%s service=%s",
        log_level, json_logs, service_name,
    )


__all__ = ["configure_logging"]
