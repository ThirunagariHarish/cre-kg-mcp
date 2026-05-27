"""
Claude AI advisor adapter.
AI is advisory only — returns recommendations, never executes trades.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from ..domain.models import Signal, Portfolio
from ..domain.exceptions import InfrastructureError

logger = logging.getLogger(__name__)

ANALYSIS_SYSTEM_PROMPT = """You are a quantitative trading analyst assistant.
Your role is ADVISORY ONLY — you analyze signals and provide recommendations,
but humans and deterministic risk systems make all final trading decisions.

Always respond with structured JSON. Be concise and data-driven.
Never recommend trades that violate position limits or risk parameters provided."""

SIGNAL_ANALYSIS_PROMPT = """Analyze this trade signal and provide a structured recommendation.

Signal: {signal_json}
Market Context: {market_context_json}

Respond with JSON:
{{
  "recommendation": "proceed" | "caution" | "reject",
  "confidence": 0.0-1.0,
  "rationale": "brief explanation",
  "suggested_position_size_pct": 0.0-10.0,
  "risk_factors": ["list of risks"],
  "catalysts": ["supporting factors"],
  "suggested_stop_loss": float or null,
  "suggested_target": float or null
}}"""


class ClaudeAIAdapter:
    """
    Anthropic Claude adapter for AI-powered trade analysis.
    
    Design principle: AI advises, humans/rules authorize.
    All Claude outputs are tagged as advisory and logged for audit.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-5-sonnet-20241022",
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._client: Any = None
        self._call_count = 0

    async def _get_client(self) -> Any:
        """Lazy-init Anthropic client."""
        if self._client is None:
            try:
                import anthropic  # type: ignore

                self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
            except ImportError:
                raise InfrastructureError("Claude AI adapter: anthropic SDK not installed", "AI_UNAVAILABLE")
        return self._client

    async def analyze(self, prompt: str, context: dict[str, Any] | None = None) -> str:
        """Raw text analysis. context is optional."""
        client = await self._get_client()
        self._call_count += 1

        try:
            if context:
                context_str = json.dumps(context, default=str, indent=2)
                full_prompt = f"{prompt}\n\nContext:\n{context_str}"
            else:
                full_prompt = prompt

            message = await client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=ANALYSIS_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": full_prompt}],
            )
            return message.content[0].text
        except Exception as exc:
            logger.error("Claude API error: %s", exc)
            raise InfrastructureError(f"Claude analysis failed: {exc}", "AI_API_ERROR") from exc

    async def structured_analyze(
        self,
        prompt: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Structured JSON analysis with fallback."""
        raw_response = await self.analyze(prompt, context)
        try:
            # Extract JSON from response
            raw_response = raw_response.strip()
            if "```json" in raw_response:
                raw_response = raw_response.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_response:
                raw_response = raw_response.split("```")[1].split("```")[0].strip()
            return json.loads(raw_response)
        except json.JSONDecodeError:
            logger.warning("Claude returned non-JSON, wrapping in dict")
            return {"raw_response": raw_response, "parse_error": True}

    async def analyze_signal(
        self,
        signal: Signal,
        market_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Analyze a trade signal."""
        prompt = SIGNAL_ANALYSIS_PROMPT.format(
            signal_json=signal.model_dump_json(indent=2),
            market_context_json=json.dumps(market_context, default=str, indent=2),
        )
        result = await self.structured_analyze(prompt, {})
        result["advisory_only"] = True
        result["model_used"] = self._model
        result["signal_id"] = signal.signal_id
        return result

    async def summarize_portfolio(self, portfolio: Portfolio) -> str:
        """Generate a portfolio summary."""
        prompt = f"""Provide a brief portfolio health summary:

Portfolio: {portfolio.model_dump_json(indent=2)}

Focus on: overall P&L, concentration risk, and top performing/losing positions.
Keep it under 200 words."""
        return await self.analyze(prompt, {})

    async def health_check(self) -> dict[str, Any]:
        """Verify Claude API connectivity."""
        try:
            client = await self._get_client()
            await client.messages.create(
                model=self._model,
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return {"status": "healthy", "model": self._model, "calls_made": self._call_count}
        except Exception as exc:
            return {"status": "unhealthy", "error": str(exc), "model": self._model}


__all__ = ["ClaudeAIAdapter"]
