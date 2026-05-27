"""Domain exception hierarchy."""
from __future__ import annotations


class TradingTerminalError(Exception):
    """Base exception for all trading terminal errors."""
    def __init__(self, message: str, code: str = "UNKNOWN_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


# ─── Domain Exceptions ───

class DomainError(TradingTerminalError):
    """Base for domain-layer errors."""


class ValidationError(DomainError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"Validation failed for {field}: {message}", "VALIDATION_ERROR")
        self.field = field


class BusinessRuleViolation(DomainError):
    def __init__(self, rule: str, message: str) -> None:
        super().__init__(f"Business rule violated [{rule}]: {message}", "BUSINESS_RULE_VIOLATION")
        self.rule = rule


# ─── Signal Exceptions ───

class SignalError(DomainError):
    pass

class SignalNotFound(SignalError):
    def __init__(self, signal_id: str) -> None:
        super().__init__(f"Signal not found: {signal_id}", "SIGNAL_NOT_FOUND")

class SignalParseError(SignalError):
    def __init__(self, message: str) -> None:
        super().__init__(f"Failed to parse signal: {message}", "SIGNAL_PARSE_ERROR")

class SignalExpired(SignalError):
    def __init__(self, signal_id: str) -> None:
        super().__init__(f"Signal has expired: {signal_id}", "SIGNAL_EXPIRED")


# ─── Order Exceptions ───

class OrderError(DomainError):
    pass

class OrderNotFound(OrderError):
    def __init__(self, order_id: str) -> None:
        super().__init__(f"Order not found: {order_id}", "ORDER_NOT_FOUND")

class InvalidOrderState(OrderError):
    def __init__(self, order_id: str, current: str, expected: str) -> None:
        super().__init__(
            f"Order {order_id} in state {current}, expected {expected}",
            "INVALID_ORDER_STATE",
        )

class OrderSubmissionFailed(OrderError):
    def __init__(self, order_id: str, reason: str) -> None:
        super().__init__(f"Order {order_id} submission failed: {reason}", "ORDER_SUBMISSION_FAILED")


# ─── Risk Exceptions ───

class RiskError(DomainError):
    pass

class RiskCheckFailed(RiskError):
    def __init__(self, check: str, detail: str) -> None:
        super().__init__(f"Risk check failed [{check}]: {detail}", "RISK_CHECK_FAILED")

class PositionLimitExceeded(RiskError):
    def __init__(self, symbol: str, current_pct: float, limit_pct: float) -> None:
        super().__init__(
            f"Position limit exceeded for {symbol}: {current_pct:.1f}% > {limit_pct:.1f}%",
            "POSITION_LIMIT_EXCEEDED",
        )

class DailyLossLimitExceeded(RiskError):
    def __init__(self, current_loss: float, limit: float) -> None:
        super().__init__(
            f"Daily loss limit exceeded: ${current_loss:.2f} > ${limit:.2f}",
            "DAILY_LOSS_LIMIT_EXCEEDED",
        )


# ─── Portfolio Exceptions ───

class PortfolioError(DomainError):
    pass

class InsufficientFunds(PortfolioError):
    def __init__(self, required: float, available: float) -> None:
        super().__init__(
            f"Insufficient funds: need ${required:.2f}, have ${available:.2f}",
            "INSUFFICIENT_FUNDS",
        )

class PositionNotFound(PortfolioError):
    def __init__(self, symbol: str) -> None:
        super().__init__(f"Position not found for symbol: {symbol}", "POSITION_NOT_FOUND")


# ─── Infrastructure Exceptions ───

class InfrastructureError(TradingTerminalError):
    pass

class BrokerConnectionError(InfrastructureError):
    def __init__(self, broker: str, reason: str) -> None:
        super().__init__(f"Broker {broker} connection failed: {reason}", "BROKER_CONNECTION_ERROR")

class BrokerOrderError(InfrastructureError):
    def __init__(self, broker: str, order_id: str, reason: str) -> None:
        super().__init__(f"Broker {broker} order error [{order_id}]: {reason}", "BROKER_ORDER_ERROR")

class EventPublishError(InfrastructureError):
    def __init__(self, topic: str, reason: str) -> None:
        super().__init__(f"Failed to publish to {topic}: {reason}", "EVENT_PUBLISH_ERROR")

class RepositoryError(InfrastructureError):
    def __init__(self, entity: str, operation: str, reason: str) -> None:
        super().__init__(f"Repository error [{entity}.{operation}]: {reason}", "REPOSITORY_ERROR")


__all__ = [
    "TradingTerminalError", "DomainError", "ValidationError", "BusinessRuleViolation",
    "SignalError", "SignalNotFound", "SignalParseError", "SignalExpired",
    "OrderError", "OrderNotFound", "InvalidOrderState", "OrderSubmissionFailed",
    "RiskError", "RiskCheckFailed", "PositionLimitExceeded", "DailyLossLimitExceeded",
    "PortfolioError", "InsufficientFunds", "PositionNotFound",
    "InfrastructureError", "BrokerConnectionError", "BrokerOrderError",
    "EventPublishError", "RepositoryError",
]
