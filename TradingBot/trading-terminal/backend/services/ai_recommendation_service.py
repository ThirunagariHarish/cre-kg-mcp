"""
AI recommendation service — advisory layer wrapping Claude adapter.
All recommendations are advisory only; risk service makes final decisions.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from ..domain.models import Signal, Portfolio, now_utc
from ..ports.outbound import IAIAdapter, IMarketDataAdapter

logger = logging.getLogger(__name__)


class AIRecommendationService:
    """
    Wraps the AI adapter to provide structured trade recommendations.

    Principle: AI advises, deterministic rules authorize.
    Every AI recommendation is tagged advisory_only=True so downstream
    consumers cannot accidentally treat it as an authorization.
    """

    def __init__(
        self,
        ai_adapter: Any,
        market_data: Any,
    ) -> None:
        self._ai = ai_adapter
        self._market_data = market_data
        self._recommendation_count = 0

    def _fallback_analysis(self, signal: Signal) -> dict[str, Any]:
        """Deterministic fallback when AI is unavailable."""
        direction = signal.direction.value if signal.direction else "buy"
        action = "BUY" if direction.lower() in ("buy", "long") else "SELL"
        sentiment = "BULLISH" if action == "BUY" else "BEARISH"
        confidence = float(signal.confidence or 0.5)
        confidence_level = "HIGH" if confidence >= 0.7 else ("MEDIUM" if confidence >= 0.5 else "LOW")

        return {
            "signal_id": signal.signal_id,
            "ticker": signal.symbol,
            "action": action,
            "confidence": confidence,
            "confidence_level": confidence_level,
            "sentiment": sentiment,
            "thesis": f"Signal from {signal.source.value if signal.source else 'unknown'} source with {confidence_level.lower()} confidence.",
            "key_factors": ["Signal source quality", "Confidence level", "Market conditions"],
            "risks": ["Market volatility", "Liquidity risk", "Execution slippage"],
            "suggested_entry": signal.suggested_entry,
            "suggested_stop_loss": signal.suggested_stop,
            "suggested_target": signal.suggested_target,
            "timeframe": signal.timeframe or "intraday",
            "model_name": "fallback",
            "generated_at": now_utc().isoformat(),
            "advisory_only": True,
            "disclaimer": "AI ADVISORY ONLY — NOT FINANCIAL ADVICE",
        }

    async def analyze_signal(
        self,
        signal: Signal,
        include_market_context: bool = True,
    ) -> dict[str, Any]:
        """
        Analyze a trade signal with AI.
        Enriches with live market data before sending to the AI adapter.
        Market data fetch failures are non-fatal.
        """
        if not self._ai:
            return self._fallback_analysis(signal)

        market_context: dict[str, Any] = {}

        if include_market_context:
            try:
                quote = await self._market_data.get_quote(signal.symbol)
                fundamentals = await self._market_data.get_fundamentals(signal.symbol)
                market_context = {
                    "quote": quote,
                    "fundamentals": {
                        k: fundamentals.get(k)
                        for k in ["trailing_pe", "market_cap", "sector", "beta", "revenue_growth"]
                    },
                }
            except Exception as exc:
                logger.warning(
                    "Failed to fetch market context for %s: %s", signal.symbol, exc
                )

        prompt = f"""Analyze this trading signal and provide a structured recommendation.

Signal: {signal.raw_message}
Symbol: {signal.symbol}
Direction: {signal.direction.value if signal.direction else 'unknown'}
Source: {signal.source.value if signal.source else 'unknown'}
Confidence: {signal.confidence}

Respond in JSON with these exact fields:
{{
  "action": "BUY|SELL|HOLD",
  "confidence": 0.0-1.0,
  "confidence_level": "HIGH|MEDIUM|LOW",
  "sentiment": "BULLISH|BEARISH|NEUTRAL",
  "thesis": "2-3 sentence analysis",
  "key_factors": ["factor1", "factor2", "factor3"],
  "risks": ["risk1", "risk2"],
  "suggested_entry": null or price,
  "suggested_stop_loss": null or price,
  "suggested_target": null or price,
  "timeframe": "intraday|1-3 days|1-2 weeks",
  "disclaimer": "AI ADVISORY ONLY — NOT FINANCIAL ADVICE"
}}"""

        try:
            raw = await self._ai.analyze(prompt, market_context)
            raw = raw.strip()
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            data = json.loads(raw)
            data["signal_id"] = signal.signal_id
            data["ticker"] = signal.symbol
            data["model_name"] = "claude-sonnet-4-6"
            data["generated_at"] = now_utc().isoformat()
            data["advisory_only"] = True
            self._recommendation_count += 1
            logger.info(
                "AI recommendation for %s: %s (confidence=%.2f)",
                signal.symbol,
                data.get("action", "unknown"),
                data.get("confidence", 0.0),
            )
            return data
        except Exception as exc:
            logger.warning("AI analysis failed: %s", exc)
            return self._fallback_analysis(signal)

    async def summarize_portfolio(self, portfolio_snapshot: dict[str, Any]) -> str:
        """
        Generate an AI portfolio health summary.
        Returns a plain-text narrative.
        """
        if not self._ai:
            return "AI summary unavailable: no AI adapter configured."
        try:
            return await self._ai.analyze(
                prompt=(
                    "Provide a brief portfolio health summary focusing on "
                    "P&L, concentration risk, and notable positions."
                ),
                context=portfolio_snapshot,
            )
        except Exception as exc:
            logger.error("Portfolio summary failed: %s", exc)
            return f"AI summary unavailable: {exc}"

    async def suggest_position_size(
        self,
        signal: Signal,
        portfolio_value: float,
        risk_tolerance: str = "moderate",
    ) -> dict[str, Any]:
        """AI-suggested position sizing. Always advisory."""
        if not self._ai:
            return {"advisory_only": True, "suggested_pct": 1.0, "error": "AI unavailable"}
        try:
            result = await self._ai.structured_analyze(
                prompt=(
                    f"Suggest position size for this trade. "
                    f"Portfolio: ${portfolio_value:,.2f}. "
                    f"Risk tolerance: {risk_tolerance}."
                ),
                context={
                    "signal": {
                        "symbol": signal.symbol,
                        "direction": signal.direction.value if signal.direction else "buy",
                        "confidence": signal.confidence,
                        "entry": signal.suggested_entry,
                        "stop": signal.suggested_stop,
                        "target": signal.suggested_target,
                    },
                    "portfolio_value": portfolio_value,
                    "risk_tolerance": risk_tolerance,
                },
            )
            result["advisory_only"] = True
            return result
        except Exception as exc:
            return {
                "advisory_only": True,
                "suggested_pct": 1.0,
                "error": str(exc),
            }

    async def health_check(self) -> dict[str, Any]:
        if not self._ai:
            return {"status": "disabled", "reason": "No AI adapter configured"}
        return await self._ai.health_check()

    @property
    def recommendation_count(self) -> int:
        return self._recommendation_count


__all__ = ["AIRecommendationService"]
