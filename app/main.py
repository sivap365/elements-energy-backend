"""
Elements Energy — Backend Assignment
=====================================
Entry point for the FastAPI application.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import orders, products
from app.db.database import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables on startup (idempotent — skips existing tables)
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Elements Energy Store API",
    description=(
        "Inventory-safe order management system. "
        "Guarantees stock correctness under concurrent requests and duplicate submissions."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(products.router)
app.include_router(orders.router)


# ── Health check ─────────────────────────────────────────────────────────────
@app.get("/health", tags=["Health"], summary="Health check")
def health():
    return {"status": "ok"}
