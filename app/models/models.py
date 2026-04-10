"""
ORM Models — 4 tables total (under the 5-table limit).

Table design rationale:
  products        — source of truth for stock; row-level lock enforces safety
  orders          — immutable order header; status reflects lifecycle
  order_items     — one row per SKU in an order; supports multi-SKU orders
  idempotency_keys— deduplication store; unique constraint prevents double-processing
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, DateTime, ForeignKey,
    UniqueConstraint, CheckConstraint, text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.database import Base


def _now():
    return datetime.now(timezone.utc)


class Product(Base):
    __tablename__ = "products"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    sku = Column(String(64), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    stock = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True),
                        nullable=False, default=_now, onupdate=_now)

    order_items = relationship("OrderItem", back_populates="product")

    # DB-level guard: stock can never go negative
    __table_args__ = (
        CheckConstraint("stock >= 0", name="ck_products_stock_non_negative"),
    )

    def __repr__(self):
        return f"<Product sku={self.sku} stock={self.stock}>"


class Order(Base):
    __tablename__ = "orders"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # Stored for idempotency lookup and audit
    idempotency_key = Column(
        String(255), nullable=False, unique=True, index=True)
    status = Column(String(32), nullable=False, default="confirmed")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    items = relationship("OrderItem", back_populates="order",
                         cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Order id={self.id} status={self.status}>"


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    order_id = Column(UUID(as_uuid=True), ForeignKey(
        "orders.id"), nullable=False, index=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey(
        "products.id"), nullable=False)
    # denormalised for fast reads
    sku = Column(String(64), nullable=False)
    quantity = Column(Integer, nullable=False)

    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="order_items")

    __table_args__ = (
        CheckConstraint(
            "quantity > 0", name="ck_order_items_quantity_positive"),
    )


class IdempotencyKey(Base):
    """
    Separate table so we can record a key *before* the order is committed.
    The unique constraint here is the first line of defence against races on
    duplicate requests.  Even if two identical requests arrive simultaneously,
    only one INSERT into this table will win; the other gets a unique-violation.
    """
    __tablename__ = "idempotency_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(255), nullable=False, unique=True, index=True)
    order_id = Column(UUID(as_uuid=True), ForeignKey(
        "orders.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint("key", name="uq_idempotency_keys_key"),
    )
