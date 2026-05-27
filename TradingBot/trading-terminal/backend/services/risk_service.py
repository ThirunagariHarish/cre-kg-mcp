"""
Risk service — deterministic risk gateway.
AI recommends, this service authorizes. All checks are deterministic rules.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..domain.models import Signal, Order, Portfolio, Position, RiskDecision, RiskDecisionStatus, OrderSide, now_utc
from ..domain.events import RiskApproved, RiskRejected
from ..domain.exceptions import RiskCheckFailed, DailyLossLimitExceeded, PositionLimitExceeded
from ..ports.outbound import IPositionRepository, IEventStore, IMessageBusPublisher
from ..adapters.kafka_publisher import KafkaTopics

logger = logging.getLogger(__name__)


@dataclass
class RiskPolicy:
    """Configurable risk parameters."""
    max_position_size_pct: float = 5.0        # Max % of portfolio per position
    max_portfolio_exposure_pct: float = 80.0   # Max total invested %
    max_daily_loss_pct: float = 3.0            # Max drawdown per day
    max_single_trade_loss_pct: float = 1.0     # Max loss on any single trade
    min_confidence: float = 0.4                # Minimum signal confidence
    min_risk_reward: float = 1.5               # Minimum R:R ratio
    max_open_positions: int = 10               # Max concurrent positions
    blacklisted_symbols: set[str] = field(default_factory=set)
    allowed_asset_classes: set[str] = field(default_factory=lambda: {"equity", "crypto"})


class RiskService:
    """
    Deterministic risk evaluation engine.

    Design: All checks are rule-based. AI input is consumed as an advisory signal
    but never bypasses these gates. A human override is logged and audited.
    """

    def __init__(
        self,
        position_repo: IPositionRepository,
        event_store: IEventStore,
        publisher: IMessageBusPublisher,
        policy: RiskPolicy | None = None,
        portfolio_cash: float = 100_000.0,
        db_session: Any = None,
        redis: Any = None,
    ) -> None:
        self._position_repo = position_repo
        self._event_store = event_store
        self._publisher = publisher
        self._policy = policy or RiskPolicy()
        self._portfolio_cash = portfolio_cash
        self._daily_pnl: float = 0.0
        self._overridden_decisions: dict[str, dict] = {}
        self._db_session = db_session
        self._redis = redis
        # In-memory halt state fallback if no DB
        self._halt_active: bool = False
        self._halt_reason: str = ""
        self._halt_activated_at: datetime | None = None

    async def _check_halt_state(self) -> bool:
        """Check DB halt_state table. Falls back to in-memory."""
        if self._db_session:
            try:
                from sqlalchemy import text
                result = await self._db_session.execute(
                    text("SELECT active FROM halt_state ORDER BY activated_at DESC LIMIT 1")
                )
                row = result.mappings().first()
                if row:
                    return bool(row["active"])
            except Exception as e:
                logger.warning("halt_state DB check failed (non-fatal): %s", e)
        return self._halt_active

    async def activate_emergency_stop(self, reason: str) -> None:
        """Activate trading halt."""
        self._halt_active = True
        self._halt_reason = reason
        self._halt_activated_at = now_utc()
        if self._db_session:
            try:
                from sqlalchemy import text
                await self._db_session.execute(
                    text("""
                        INSERT INTO halt_state (active, reason, activated_at)
                        VALUES (true, :reason, now())
                        ON CONFLICT DO NOTHING
                    """),
                    {"reason": reason},
                )
                await self._db_session.commit()
            except Exception as e:
                logger.warning("Failed to persist halt_state to DB: %s", e)
        logger.critical("EMERGENCY STOP ACTIVATED: %s", reason)

    async def deactivate_emergency_stop(self) -> None:
        """Deactivate trading halt."""
        self._halt_active = False
        self._halt_reason = ""
        self._halt_activated_at = None
        if self._db_session:
            try:
                from sqlalchemy import text
                await self._db_session.execute(
                    text("UPDATE halt_state SET active = false")
                )
                await self._db_session.commit()
            except Exception as e:
                logger.warning("Failed to update halt_state in DB: %s", e)
        logger.info("Emergency stop deactivated")

    async def get_halt_state(self) -> dict[str, Any]:
        """Return current halt state."""
        if self._db_session:
            try:
                from sqlalchemy import text
                result = await self._db_session.execute(
                    text("SELECT active, reason, activated_at FROM halt_state ORDER BY activated_at DESC LIMIT 1")
                )
                row = result.mappings().first()
                if row:
                    return {
                        "active": bool(row["active"]),
                        "reason": row.get("reason", ""),
                        "activated_at": row.get("activated_at"),
                    }
            except Exception as e:
                logger.warning("Failed to read halt_state: %s", e)
        return {
            "active": self._halt_active,
            "reason": self._halt_reason,
            "activated_at": self._halt_activated_at,
        }

    async def evaluate_order(
        self,
        order: Order,
        portfolio_value: float,
        current_positions: list[Position],
    ) -> RiskDecision:
        """
        Run risk checks against a proposed order.
        Returns RiskDecision with full audit trail.
        """
        checks_passed: list[str] = []
        checks_failed: list[str] = []

        # Check 1: Emergency stop
        halt = await self._check_halt_state()
        if halt:
            checks_failed.append("emergency_stop_active")
            return RiskDecision(
                signal_id=order.signal_id or order.order_id,
                order_id=order.order_id,
                status=RiskDecisionStatus.REJECTED,
                reason="emergency_stop_active",
                checks_passed=checks_passed,
                checks_failed=checks_failed,
            )

        checks_passed.append("no_emergency_stop")

        # Check 2: Blacklisted symbol
        if order.symbol.upper() in self._policy.blacklisted_symbols:
            checks_failed.append("symbol_blacklisted")
        else:
            checks_passed.append("symbol_not_blacklisted")

        # Check 3: Asset class allowed
        if order.asset_class.value not in self._policy.allowed_asset_classes:
            checks_failed.append("asset_class_not_allowed")
        else:
            checks_passed.append("asset_class_allowed")

        # Check 4: Order quantity positive
        if order.quantity <= 0:
            checks_failed.append("invalid_quantity")
        else:
            checks_passed.append("quantity_valid")

        # Check 5: Max open positions
        open_count = len([p for p in current_positions if p.status.value == "open"])
        if open_count >= self._policy.max_open_positions:
            checks_failed.append("max_positions_exceeded")
        else:
            checks_passed.append("position_count_ok")

        # Check 6: Position size % of portfolio
        order_value = order.quantity * (order.limit_price or portfolio_value * 0.01)
        position_pct = (order_value / max(portfolio_value, 1.0)) * 100.0
        if position_pct > self._policy.max_position_size_pct:
            checks_failed.append("position_size_exceeded")
        else:
            checks_passed.append("position_size_ok")

        # Check 7: Total portfolio exposure
        total_exposure = sum(
            p.market_value for p in current_positions if p.status.value == "open"
        )
        exposure_pct = ((total_exposure + order_value) / max(portfolio_value, 1.0)) * 100.0
        if exposure_pct > self._policy.max_portfolio_exposure_pct:
            checks_failed.append("portfolio_exposure_exceeded")
        else:
            checks_passed.append("portfolio_exposure_ok")

        # Check 8: Daily loss limit
        daily_loss_pct = abs(min(0.0, self._daily_pnl) / max(portfolio_value, 1.0)) * 100.0
        if daily_loss_pct >= self._policy.max_daily_loss_pct:
            checks_failed.append("daily_loss_limit_exceeded")
        else:
            checks_passed.append("daily_loss_ok")

        # Check 9: Duplicate order protection via Redis (same symbol+side in last 60s)
        if self._redis:
            try:
                dup_key = f"order:dup:{order.symbol.upper()}:{order.side.value}"
                existing = await self._redis.get(dup_key)
                if existing:
                    checks_failed.append("duplicate_order")
                    logger.warning("Duplicate order detected: %s", dup_key)
                else:
                    checks_passed.append("no_duplicate_order")
            except Exception as e:
                logger.warning("Redis dup check failed (non-fatal): %s", e)
                checks_passed.append("dup_check_skipped")
        else:
            checks_passed.append("dup_check_skipped")

        # Check 10: Market hours — warn only, don't reject
        now_et = datetime.now(timezone.utc)
        hour_utc = now_et.hour
        weekday = now_et.weekday()
        # US market: 9:30 AM - 4:00 PM ET = 14:30 - 21:00 UTC
        market_open = weekday < 5 and (hour_utc > 14 or (hour_utc == 14 and now_et.minute >= 30)) and hour_utc < 21
        if not market_open:
            logger.warning("Order submitted outside market hours (proceeding for paper trading)")
            checks_passed.append("market_hours_warning_only")
        else:
            checks_passed.append("market_hours_ok")

        if checks_failed:
            status = RiskDecisionStatus.REJECTED
            reason = "; ".join(checks_failed)
        else:
            status = RiskDecisionStatus.APPROVED
            reason = "all_checks_passed"

        decision = RiskDecision(
            signal_id=order.signal_id or order.order_id,
            order_id=order.order_id,
            status=status,
            reason=reason,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            portfolio_exposure_pct=round(exposure_pct, 2),
        )

        # Publish event (non-fatal)
        try:
            if status == RiskDecisionStatus.APPROVED:
                event = RiskApproved(
                    aggregate_id=decision.decision_id,
                    signal_id=decision.signal_id,
                    approved_quantity=order.quantity,
                    approved_entry=order.limit_price or 0.0,
                    max_loss=0.0,
                    portfolio_exposure_pct=round(exposure_pct, 2),
                    checks_passed=checks_passed,
                )
                await self._event_store.append(event)
            else:
                event = RiskRejected(
                    aggregate_id=decision.decision_id,
                    signal_id=decision.signal_id,
                    reason=reason,
                    checks_failed=checks_failed,
                    portfolio_exposure_current=total_exposure,
                )
                await self._event_store.append(event)
        except Exception as e:
            logger.warning("Failed to persist risk event (non-fatal): %s", e)

        # Set duplicate-order guard in Redis
        if status == RiskDecisionStatus.APPROVED and self._redis:
            try:
                dup_key = f"order:dup:{order.symbol.upper()}:{order.side.value}"
                await self._redis.set(dup_key, order.order_id, ex=60)
            except Exception as e:
                logger.warning("Redis dup-set failed (non-fatal): %s", e)

        logger.info(
            "Risk %s [%s]: %s (checks_failed=%s)",
            status.value.upper(), decision.decision_id, order.symbol, checks_failed,
        )
        return decision

    async def evaluate_signal(
        self,
        signal: Signal,
        proposed_quantity: float,
        proposed_entry: float,
        ai_recommendation: dict[str, Any] | None = None,
    ) -> RiskDecision:
        """
        Run all risk checks against a proposed trade.
        Returns RiskDecision with full audit trail of checks run.
        """
        checks_passed: list[str] = []
        checks_failed: list[str] = []

        open_positions = await self._position_repo.list_open_positions()
        portfolio_value = self._portfolio_cash + sum(
            p.market_value for p in open_positions
        )

        # 1. Symbol blacklist
        if signal.symbol.upper() in self._policy.blacklisted_symbols:
            checks_failed.append(f"symbol_blacklisted:{signal.symbol}")
            return await self._reject(signal, checks_passed, checks_failed, "Symbol is blacklisted", portfolio_value)
        checks_passed.append("symbol_not_blacklisted")

        # 2. Asset class allowed
        if signal.asset_class.value not in self._policy.allowed_asset_classes:
            checks_failed.append(f"asset_class_not_allowed:{signal.asset_class.value}")
            return await self._reject(signal, checks_passed, checks_failed, "Asset class not allowed", portfolio_value)
        checks_passed.append("asset_class_allowed")

        # 3. Confidence threshold
        if signal.confidence < self._policy.min_confidence:
            checks_failed.append(f"confidence_too_low:{signal.confidence:.2f}<{self._policy.min_confidence}")
            return await self._reject(signal, checks_passed, checks_failed, f"Signal confidence too low: {signal.confidence:.2f}", portfolio_value)
        checks_passed.append("confidence_sufficient")

        # 4. Max open positions
        if len(open_positions) >= self._policy.max_open_positions:
            checks_failed.append(f"max_positions_reached:{len(open_positions)}")
            return await self._reject(signal, checks_passed, checks_failed, "Maximum open positions reached", portfolio_value)
        checks_passed.append("position_count_ok")

        # 5. Position size check — auto-resize if oversized rather than hard reject
        trade_value = proposed_quantity * proposed_entry
        position_size_pct = (trade_value / portfolio_value) * 100.0 if portfolio_value > 0 else 100.0
        if position_size_pct > self._policy.max_position_size_pct:
            max_value = portfolio_value * (self._policy.max_position_size_pct / 100.0)
            proposed_quantity = max_value / proposed_entry if proposed_entry > 0 else 0
            trade_value = proposed_quantity * proposed_entry
            position_size_pct = self._policy.max_position_size_pct
            checks_passed.append(f"position_resized_to_{self._policy.max_position_size_pct:.1f}pct")
        else:
            checks_passed.append(f"position_size_ok:{position_size_pct:.1f}pct")

        # 6. Portfolio exposure
        current_exposure = sum(p.market_value for p in open_positions)
        projected_exposure_pct = ((current_exposure + trade_value) / portfolio_value) * 100.0 if portfolio_value > 0 else 100.0
        if projected_exposure_pct > self._policy.max_portfolio_exposure_pct:
            checks_failed.append(f"portfolio_overexposed:{projected_exposure_pct:.1f}%")
            return await self._reject(signal, checks_passed, checks_failed, f"Portfolio would be {projected_exposure_pct:.1f}% exposed", portfolio_value)
        checks_passed.append(f"portfolio_exposure_ok:{projected_exposure_pct:.1f}pct")

        # 7. Daily loss limit
        daily_loss_pct = abs(min(0, self._daily_pnl) / portfolio_value) * 100.0 if portfolio_value > 0 else 0.0
        if daily_loss_pct >= self._policy.max_daily_loss_pct:
            checks_failed.append(f"daily_loss_limit:{daily_loss_pct:.1f}%>={self._policy.max_daily_loss_pct}%")
            return await self._reject(signal, checks_passed, checks_failed, f"Daily loss limit reached: {daily_loss_pct:.1f}%", portfolio_value)
        checks_passed.append(f"daily_loss_ok:{daily_loss_pct:.1f}pct")

        # 8. Risk/reward check
        if signal.suggested_stop and signal.suggested_target and proposed_entry:
            risk_per_share = abs(proposed_entry - signal.suggested_stop)
            reward_per_share = abs(signal.suggested_target - proposed_entry)
            if risk_per_share > 0:
                rr_ratio = reward_per_share / risk_per_share
                if rr_ratio < self._policy.min_risk_reward:
                    checks_failed.append(f"rr_ratio_low:{rr_ratio:.2f}<{self._policy.min_risk_reward}")
                    return await self._reject(signal, checks_passed, checks_failed, f"R:R ratio too low: {rr_ratio:.2f}", portfolio_value)
                checks_passed.append(f"rr_ratio_ok:{rr_ratio:.2f}")

        # 9. Sufficient cash for buy orders
        if signal.direction == OrderSide.BUY:
            cash_available = self._portfolio_cash
            if trade_value > cash_available * 0.95:
                checks_failed.append(f"insufficient_cash:{trade_value:.2f}>{cash_available:.2f}")
                return await self._reject(signal, checks_passed, checks_failed, "Insufficient cash", portfolio_value)
            checks_passed.append("cash_sufficient")

        max_loss = 0.0
        if signal.suggested_stop and proposed_entry:
            max_loss = abs(proposed_entry - signal.suggested_stop) * proposed_quantity

        risk_score = 1.0 - (len(checks_failed) / max(1, len(checks_passed) + len(checks_failed)))

        decision = RiskDecision(
            signal_id=signal.signal_id,
            status=RiskDecisionStatus.APPROVED,
            reason="All risk checks passed",
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            position_size_recommended=round(proposed_quantity, 4),
            max_loss_allowed=round(max_loss, 2),
            portfolio_exposure_pct=round(projected_exposure_pct, 2),
        )

        event = RiskApproved(
            aggregate_id=decision.decision_id,
            signal_id=signal.signal_id,
            approved_quantity=round(proposed_quantity, 4),
            approved_entry=proposed_entry,
            max_loss=round(max_loss, 2),
            portfolio_exposure_pct=round(projected_exposure_pct, 2),
            checks_passed=checks_passed,
            risk_score=round(risk_score, 3),
        )
        try:
            await self._publisher.publish(KafkaTopics.RISK_DECISIONS, event)
        except Exception as e:
            logger.warning("Kafka publish failed (non-fatal): %s", e)

        logger.info(
            "Risk APPROVED [%s]: %s (qty=%.4f, exposure=%.1f%%, checks=%d passed)",
            decision.decision_id, signal.symbol, proposed_quantity,
            projected_exposure_pct, len(checks_passed),
        )
        return decision

    async def _reject(
        self,
        signal: Signal,
        checks_passed: list[str],
        checks_failed: list[str],
        reason: str,
        portfolio_value: float,
    ) -> RiskDecision:
        decision = RiskDecision(
            signal_id=signal.signal_id,
            status=RiskDecisionStatus.REJECTED,
            reason=reason,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
        )
        event = RiskRejected(
            aggregate_id=decision.decision_id,
            signal_id=signal.signal_id,
            reason=reason,
            checks_failed=checks_failed,
            portfolio_exposure_current=0.0,
        )
        try:
            await self._publisher.publish(KafkaTopics.RISK_DECISIONS, event)
        except Exception as e:
            logger.warning("Kafka publish failed (non-fatal): %s", e)
        logger.warning(
            "Risk REJECTED [%s]: %s — %s (failed: %s)",
            decision.decision_id, signal.symbol, reason, checks_failed,
        )
        return decision

    async def get_risk_status(self) -> dict[str, Any]:
        """Return current risk policy and live portfolio risk metrics."""
        open_positions = await self._position_repo.list_open_positions()
        halt_state = await self.get_halt_state()
        return {
            "halt_state": halt_state,
            "policy": {
                "max_position_size_pct": self._policy.max_position_size_pct,
                "max_portfolio_exposure_pct": self._policy.max_portfolio_exposure_pct,
                "max_daily_loss_pct": self._policy.max_daily_loss_pct,
                "min_confidence": self._policy.min_confidence,
                "max_open_positions": self._policy.max_open_positions,
                "blacklisted_symbols": list(self._policy.blacklisted_symbols),
                "allowed_asset_classes": list(self._policy.allowed_asset_classes),
            },
            "current": {
                "open_positions": len(open_positions),
                "daily_pnl": self._daily_pnl,
                "portfolio_cash": self._portfolio_cash,
            },
        }

    async def override_decision(
        self,
        decision_id: str,
        override_by: str,
        reason: str,
    ) -> RiskDecision:
        logger.warning(
            "RISK OVERRIDE: decision=%s by=%s reason=%s",
            decision_id, override_by, reason,
        )
        self._overridden_decisions[decision_id] = {
            "override_by": override_by,
            "reason": reason,
            "timestamp": now_utc().isoformat(),
        }
        return RiskDecision(
            signal_id=decision_id,
            status=RiskDecisionStatus.APPROVED,
            reason=f"Manual override by {override_by}: {reason}",
            checks_passed=["manual_override"],
            checks_failed=[],
        )

    def update_daily_pnl(self, pnl_delta: float) -> None:
        self._daily_pnl += pnl_delta


__all__ = ["RiskService", "RiskPolicy"]
