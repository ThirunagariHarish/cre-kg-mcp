"""Signal ingestion and management endpoints."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ...services.ingestion_service import IngestionService, DuplicateSignalError
from ...services.parser_service import ParserService
from ...services.ai_recommendation_service import AIRecommendationService
from ..dependencies import get_ingestion_service, get_parser_service, get_ai_recommendation_service, CurrentUser, get_current_user

router = APIRouter(prefix="/api/signals", tags=["signals"])


class IngestRequest(BaseModel):
    source: str = "manual"
    channel_id: str = "api"
    author: str = "api-user"
    content: str = Field(..., min_length=1, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParseRequest(BaseModel):
    raw_message_id: str
    source: str = "manual"
    content: str = Field(..., min_length=1)


class SignalIngestRequest(BaseModel):
    """Structured signal ingest request."""
    source: str = "manual"
    raw_text: str = Field(..., min_length=1, max_length=2000)
    symbol: str | None = None
    channel: str = "default"
    author: str = "system"
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("/ingest-signal", status_code=201, summary="Ingest a structured signal")
async def ingest_signal(
    body: SignalIngestRequest,
    service: Annotated[IngestionService, Depends(get_ingestion_service)],
    _: CurrentUser,
) -> dict[str, Any]:
    """Ingest a structured signal directly into the DB and Kafka."""
    try:
        signal = await service.ingest_signal(
            source=body.source,
            raw_text=body.raw_text,
            symbol=body.symbol,
            channel=body.channel,
            author=body.author,
            metadata=body.metadata,
        )
        return {"signal_id": signal.signal_id, "status": "queued"}
    except DuplicateSignalError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/feed", summary="Get signal feed")
async def signal_feed(
    service: Annotated[IngestionService, Depends(get_ingestion_service)],
    _: CurrentUser,
    limit: int = Query(20, ge=1, le=200),
) -> list[dict[str, Any]]:
    """Latest signals feed."""
    signals = await service.list_signals(limit=limit)
    return [s.model_dump() for s in signals]


@router.post("/ingest", summary="Ingest a raw message")
async def ingest_message(
    body: IngestRequest,
    service: Annotated[IngestionService, Depends(get_ingestion_service)],
) -> dict[str, Any]:
    message_id = await service.ingest_raw_message(
        source=body.source,
        channel_id=body.channel_id,
        author=body.author,
        content=body.content,
        metadata=body.metadata,
    )
    return {"message_id": message_id, "status": "ingested"}


@router.post("/parse", summary="Parse a raw message into a trade idea")
async def parse_message(
    body: ParseRequest,
    parser: Annotated[ParserService, Depends(get_parser_service)],
) -> dict[str, Any]:
    signal = await parser.parse_message(
        raw_message_id=body.raw_message_id,
        source=body.source,
        content=body.content,
    )
    if not signal:
        raise HTTPException(status_code=422, detail="Could not extract trade idea from message")
    return signal.model_dump()


@router.get("/", summary="List signals")
async def list_signals(
    service: Annotated[IngestionService, Depends(get_ingestion_service)],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    symbol: str | None = Query(None),
) -> dict[str, Any]:
    signals = await service.list_signals(limit=limit, offset=offset, symbol=symbol)
    return {"signals": [s.model_dump() for s in signals], "count": len(signals)}


@router.get("/{signal_id}", summary="Get signal by ID")
async def get_signal(
    signal_id: str,
    service: Annotated[IngestionService, Depends(get_ingestion_service)],
) -> dict[str, Any]:
    signal = await service.get_signal(signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail=f"Signal {signal_id} not found")
    return signal.model_dump()


@router.post("/{signal_id}/analyze", summary="Get AI analysis for a signal")
async def analyze_signal(
    signal_id: str,
    service: Annotated[IngestionService, Depends(get_ingestion_service)],
    ai_service: Annotated[AIRecommendationService, Depends(get_ai_recommendation_service)],
) -> dict[str, Any]:
    signal = await service.get_signal(signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail=f"Signal {signal_id} not found")
    return await ai_service.analyze_signal(signal)
