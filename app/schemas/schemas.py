"""
Pydantic v2 schemas — strict request validation and clean API responses.
"""

from __future__ import annotations
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────── Product ────────────────────────────────────────

class ProductCreate(BaseModel):
    sku: str = Field(..., min_length=1, max_length=64, examples=["SKU-1"])
    name: str = Field(..., min_length=1, max_length=255,
                      examples=["Widget Pro"])
    stock: int = Field(..., ge=0, examples=[100])


class ProductResponse(BaseModel):
    id: UUID
    sku: str
    name: str
    stock: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─────────────────────────── Order ──────────────────────────────────────────

class OrderItemRequest(BaseModel):
    sku: str = Field(..., min_length=1, max_length=64, examples=["SKU-1"])
    quantity: int = Field(..., ge=1, examples=[2])


class OrderCreate(BaseModel):
    idempotency_key: str = Field(..., min_length=1,
                                 max_length=255, examples=["abc-123"])
    items: list[OrderItemRequest] = Field(..., min_length=1)

    @field_validator("items")
    @classmethod
    def no_duplicate_skus(cls, items: list[OrderItemRequest]) -> list[OrderItemRequest]:
        skus = [i.sku for i in items]
        if len(skus) != len(set(skus)):
            raise ValueError(
                "Duplicate SKUs in a single order are not allowed.")
        return items


class OrderItemResponse(BaseModel):
    sku: str
    quantity: int

    model_config = {"from_attributes": True}


class OrderResponse(BaseModel):
    id: UUID
    idempotency_key: str
    status: str
    items: list[OrderItemResponse]
    created_at: datetime

    model_config = {"from_attributes": True}


# ─────────────────────────── Errors ─────────────────────────────────────────

class ErrorResponse(BaseModel):
    detail: str
