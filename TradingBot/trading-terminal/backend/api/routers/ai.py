"""AI recommendation endpoints."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...services.ai_recommendation_service import AIRecommendationService
from ...services.ingestion_service import IngestionService
from ...services.portfolio_service import PortfolioService
from ..dependencies import get_ai_recommendation_service, get_ingestion_service, get_portfolio_service

router = APIRouter(prefix="/api/ai", tags=["ai"])


class PortfolioAnalysisRequest(BaseModel):
    pass  # Uses current portfolio state


@router.get("/health", summary="AI service health check")
async def ai_health(
    service: Annotated[AIRecommendationService, Depends(get_ai_recommendation_service)],
) -> dict[str, Any]:
    return await service.health_check()


@router.post("/analyze/{signal_id}", summary="AI analysis for a signal")
async def analyze_signal(
    signal_id: str,
    ingestion: Annotated[IngestionService, Depends(get_ingestion_service)],
    ai_service: Annotated[AIRecommendationService, Depends(get_ai_recommendation_service)],
) -> dict[str, Any]:
    signal = await ingestion.get_signal(signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail=f"Signal {signal_id} not found")
    return await ai_service.analyze_signal(signal)


@router.get("/portfolio/summary", summary="AI portfolio summary")
async def portfolio_summary(
    portfolio_service: Annotated[PortfolioService, Depends(get_portfolio_service)],
    ai_service: Annotated[AIRecommendationService, Depends(get_ai_recommendation_service)],
) -> dict[str, Any]:
    snapshot = await portfolio_service.get_portfolio_snapshot()
    summary = await ai_service.summarize_portfolio(snapshot)
    return {"summary": summary, "portfolio": snapshot}
