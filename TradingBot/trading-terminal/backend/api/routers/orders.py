"""Order management endpoints."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ...domain.models import OrderSide, OrderType, AssetClass
from ...services.order_gateway import OrderGatewayService
from ...services.execution_service import ExecutionService
from ..dependencies import get_order_gateway, get_execution_service

router = APIRouter(prefix="/api/orders", tags=["orders"])


class CreateOrderRequest(BaseModel):
    signal_id: str | None = None
    symbol: str = Field(..., min_length=1, max_length=10)
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    quantity: float = Field(..., gt=0)
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: str = "day"
    asset_class: AssetClass = AssetClass.EQUITY


@router.post("/", summary="Create and execute an order")
async def create_order(
    body: CreateOrderRequest,
    gateway: Annotated[OrderGatewayService, Depends(get_order_gateway)],
    execution: Annotated[ExecutionService, Depends(get_execution_service)],
) -> dict[str, Any]:
    order = await gateway.create_order_from_signal(
        signal_id=body.signal_id or "manual",
        symbol=body.symbol,
        side=body.side,
        quantity=body.quantity,
        entry_price=body.limit_price,
        stop_price=body.stop_price,
        order_type=body.order_type,
        time_in_force=body.time_in_force,
        asset_class=body.asset_class,
    )
    # Execute immediately
    order = await execution.execute_order(order)
    return order.model_dump()


@router.get("/", summary="List orders")
async def list_orders(
    gateway: Annotated[OrderGatewayService, Depends(get_order_gateway)],
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    orders = await gateway.list_orders(status=status, limit=limit)
    return {"orders": [o.model_dump() for o in orders], "count": len(orders)}


@router.get("/open", summary="Get open orders")
async def get_open_orders(
    gateway: Annotated[OrderGatewayService, Depends(get_order_gateway)],
) -> dict[str, Any]:
    orders = await gateway.get_open_orders()
    return {"orders": [o.model_dump() for o in orders], "count": len(orders)}


@router.get("/{order_id}", summary="Get order by ID")
async def get_order(
    order_id: str,
    gateway: Annotated[OrderGatewayService, Depends(get_order_gateway)],
) -> dict[str, Any]:
    order = await gateway.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    return order.model_dump()


@router.delete("/{order_id}", summary="Cancel an order")
async def cancel_order(
    order_id: str,
    gateway: Annotated[OrderGatewayService, Depends(get_order_gateway)],
    reason: str = Query("user_requested"),
) -> dict[str, Any]:
    order = await gateway.cancel_order(order_id, reason=reason)
    return {"order_id": order_id, "status": order.status.value}
