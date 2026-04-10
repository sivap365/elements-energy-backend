from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.models import Order
from app.schemas.schemas import OrderCreate, OrderResponse
from app.services.order_service import (
    InsufficientStockError,
    ProductNotFoundError,
    create_order,
)

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post(
    "",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Place an order",
    responses={
        200: {"description": "Duplicate request — original order returned (idempotent replay)"},
        409: {"description": "Insufficient stock"},
        404: {"description": "Product SKU not found"},
    },
)
def place_order(payload: OrderCreate, db: Session = Depends(get_db)):
    """
    Place an order for one or more products.

    - **Idempotent**: Sending the same `idempotency_key` twice returns the
      original order without creating a duplicate or touching stock again.
    - **Atomic**: Either all items are reserved or none are.
    - **Concurrent-safe**: Row-level locking ensures only one order wins
      when multiple users race for the last unit.
    """
    try:
        order_response, is_new = create_order(db, payload)
    except ProductNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except InsufficientStockError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    # RFC-compliant: return 200 (not 201) on idempotent replay
    from fastapi.responses import JSONResponse
    if not is_new:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=order_response.model_dump(mode="json"),
        )

    return order_response


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    summary="Get an order by ID",
)
def get_order(order_id: UUID, db: Session = Depends(get_db)):
    """
    Fetch a confirmed order and its line items by order UUID.
    """
    order = db.execute(
        select(Order).where(Order.id == order_id)
    ).scalar_one_or_none()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order '{order_id}' not found.",
        )
    return order
