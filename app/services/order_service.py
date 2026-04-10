"""
Order service — the critical path.

Concurrency safety strategy:
  1. INSERT into idempotency_keys first (unique constraint).
     If two identical requests race, exactly one INSERT wins.
     The loser gets an IntegrityError → return cached response.

  2. For each product SKU in the order, acquire a row-level exclusive
     lock with SELECT ... FOR UPDATE.
     PostgreSQL serialises all writers on the same row here.
     No two transactions can hold the lock simultaneously.

  3. Check stock AFTER acquiring the lock (not before).
     Checking before the lock is a TOCTOU (time-of-check / time-of-use)
     race condition — another transaction could drain stock between the
     check and the update.

  4. Deduct stock atomically inside the same transaction.
     The DB CHECK constraint (stock >= 0) is the last line of defence;
     it prevents any bug from producing negative stock.

  5. Commit once. Either everything succeeds or everything rolls back.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.models import IdempotencyKey, Order, OrderItem, Product
from app.schemas.schemas import OrderCreate, OrderResponse


class InsufficientStockError(Exception):
    def __init__(self, sku: str, requested: int, available: int):
        self.sku = sku
        self.requested = requested
        self.available = available
        super().__init__(
            f"Insufficient stock for SKU '{sku}': "
            f"requested {requested}, available {available}."
        )


class ProductNotFoundError(Exception):
    def __init__(self, sku: str):
        self.sku = sku
        super().__init__(f"Product with SKU '{sku}' not found.")


def create_order(db: Session, payload: OrderCreate) -> tuple[OrderResponse, bool]:
    """
    Create an order atomically.

    Returns (OrderResponse, is_new) where is_new=False means the response
    was replayed from a previous identical request (idempotent replay).

    Raises:
        ProductNotFoundError      — unknown SKU
        InsufficientStockError    — not enough stock for at least one SKU
    """

    # ── Step 1: Idempotency guard ──────────────────────────────────────────
    # Check if we've seen this key before (fast path — no locks needed).
    existing_key = db.execute(
        select(IdempotencyKey).where(
            IdempotencyKey.key == payload.idempotency_key)
    ).scalar_one_or_none()

    if existing_key and existing_key.order_id:
        # Replay: return the original order without touching stock.
        order = db.get(Order, existing_key.order_id)
        return _to_response(order), False

    # ── Step 2: Lock all products upfront (sorted to prevent deadlocks) ───
    # Sorting SKUs ensures every concurrent transaction acquires locks in the
    # same order, which eliminates the classic deadlock cycle.
    skus = sorted(item.sku for item in payload.items)

    locked_products: dict[str, Product] = {}
    for sku in skus:
        product = db.execute(
            select(Product)
            .where(Product.sku == sku)
            .with_for_update()          # Exclusive row lock
        ).scalar_one_or_none()

        if product is None:
            raise ProductNotFoundError(sku)

        locked_products[sku] = product

    # ── Step 3: Validate stock AFTER acquiring locks ───────────────────────
    sku_to_quantity: dict[str, int] = {
        item.sku: item.quantity for item in payload.items}

    for sku, product in locked_products.items():
        requested = sku_to_quantity[sku]
        if product.stock < requested:
            raise InsufficientStockError(sku, requested, product.stock)

    # ── Step 4: All checks pass — create the order ────────────────────────
    order = Order(
        idempotency_key=payload.idempotency_key,
        status="confirmed",
    )
    db.add(order)
    db.flush()  # Populate order.id without committing

    for sku, product in locked_products.items():
        quantity = sku_to_quantity[sku]

        # Deduct stock atomically (still within the locked transaction)
        product.stock -= quantity

        order_item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            sku=sku,
            quantity=quantity,
        )
        db.add(order_item)

    # ── Step 5: Record idempotency key linked to this order ───────────────
    try:
        idem_record = IdempotencyKey(
            key=payload.idempotency_key, order_id=order.id)
        db.add(idem_record)
        db.commit()
    except IntegrityError:
        # Extremely rare race: two threads passed the read check simultaneously.
        # The unique constraint on idempotency_keys catches it.
        db.rollback()
        # Re-query and replay
        existing_key = db.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.key == payload.idempotency_key)
        ).scalar_one_or_none()
        if existing_key and existing_key.order_id:
            order = db.get(Order, existing_key.order_id)
            return _to_response(order), False
        raise  # Unexpected — let the caller handle it

    db.refresh(order)
    return _to_response(order), True


def _to_response(order: Order) -> OrderResponse:
    return OrderResponse.model_validate(order)
