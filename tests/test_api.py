"""
Tests for Elements Energy backend.
Uses real PostgreSQL on port 5433 (same Docker container).

Run with:
    python -m pytest tests/ -v
"""

import threading
import uuid
from collections import Counter

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.main import app

# ── Real PostgreSQL — same Docker container, port 5433 ────────────────────
TEST_DATABASE_URL = "postgresql://elements:elements_pass@127.0.0.1:5433/elements_energy"

test_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
TestingSession = sessionmaker(
    autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    """Drop and recreate all tables before every test for full isolation."""
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client():
    return TestClient(app)


def make_product(client, sku="SKU-TEST", stock=10):
    resp = client.post(
        "/products", json={"sku": sku, "name": "Test Widget", "stock": stock})
    assert resp.status_code == 201, resp.text
    return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Product endpoints
# ─────────────────────────────────────────────────────────────────────────────

class TestProductEndpoints:

    def test_create_product_success(self, client):
        resp = client.post(
            "/products", json={"sku": "SKU-1", "name": "Widget", "stock": 50})
        assert resp.status_code == 201
        data = resp.json()
        assert data["sku"] == "SKU-1"
        assert data["stock"] == 50

    def test_create_product_duplicate_sku(self, client):
        make_product(client, sku="SKU-DUP")
        resp = client.post(
            "/products", json={"sku": "SKU-DUP", "name": "Dup", "stock": 5})
        assert resp.status_code == 409

    def test_get_product_success(self, client):
        make_product(client, sku="SKU-GET", stock=20)
        resp = client.get("/products/SKU-GET")
        assert resp.status_code == 200
        assert resp.json()["stock"] == 20

    def test_get_product_not_found(self, client):
        resp = client.get("/products/DOES-NOT-EXIST")
        assert resp.status_code == 404

    def test_create_product_negative_stock_rejected(self, client):
        resp = client.post(
            "/products", json={"sku": "SKU-BAD", "name": "Bad", "stock": -1})
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# 2. Order — happy path
# ─────────────────────────────────────────────────────────────────────────────

class TestOrderHappyPath:

    def test_create_order_success(self, client):
        make_product(client, sku="SKU-1", stock=10)
        resp = client.post("/orders", json={
            "idempotency_key": str(uuid.uuid4()),
            "items": [{"sku": "SKU-1", "quantity": 3}],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "confirmed"
        assert data["items"][0]["sku"] == "SKU-1"
        assert data["items"][0]["quantity"] == 3

    def test_stock_is_reduced_after_order(self, client):
        make_product(client, sku="SKU-2", stock=10)
        client.post("/orders", json={
            "idempotency_key": str(uuid.uuid4()),
            "items": [{"sku": "SKU-2", "quantity": 4}],
        })
        stock_now = client.get("/products/SKU-2").json()["stock"]
        assert stock_now == 6

    def test_get_order_by_id(self, client):
        make_product(client, sku="SKU-3", stock=5)
        create_resp = client.post("/orders", json={
            "idempotency_key": str(uuid.uuid4()),
            "items": [{"sku": "SKU-3", "quantity": 1}],
        })
        order_id = create_resp.json()["id"]
        get_resp = client.get(f"/orders/{order_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == order_id

    def test_get_order_not_found(self, client):
        resp = client.get(f"/orders/{uuid.uuid4()}")
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# 3. Stock exhaustion
# ─────────────────────────────────────────────────────────────────────────────

class TestStockExhaustion:

    def test_order_rejected_when_insufficient_stock(self, client):
        make_product(client, sku="SKU-LOW", stock=2)
        resp = client.post("/orders", json={
            "idempotency_key": str(uuid.uuid4()),
            "items": [{"sku": "SKU-LOW", "quantity": 5}],
        })
        assert resp.status_code == 409
        assert "Insufficient stock" in resp.json()["detail"]

    def test_stock_unchanged_after_rejection(self, client):
        make_product(client, sku="SKU-SAFE", stock=3)
        client.post("/orders", json={
            "idempotency_key": str(uuid.uuid4()),
            "items": [{"sku": "SKU-SAFE", "quantity": 99}],
        })
        assert client.get("/products/SKU-SAFE").json()["stock"] == 3

    def test_zero_stock_rejected(self, client):
        make_product(client, sku="SKU-ZERO", stock=0)
        resp = client.post("/orders", json={
            "idempotency_key": str(uuid.uuid4()),
            "items": [{"sku": "SKU-ZERO", "quantity": 1}],
        })
        assert resp.status_code == 409

    def test_unknown_sku_returns_404(self, client):
        resp = client.post("/orders", json={
            "idempotency_key": str(uuid.uuid4()),
            "items": [{"sku": "GHOST-SKU", "quantity": 1}],
        })
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# 4. Idempotency
# ─────────────────────────────────────────────────────────────────────────────

class TestIdempotency:

    def test_same_key_returns_same_order(self, client):
        make_product(client, sku="SKU-IDEM", stock=10)
        key = str(uuid.uuid4())
        payload = {"idempotency_key": key, "items": [
            {"sku": "SKU-IDEM", "quantity": 2}]}

        resp1 = client.post("/orders", json=payload)
        resp2 = client.post("/orders", json=payload)

        assert resp1.status_code == 201
        assert resp2.status_code == 200
        assert resp1.json()["id"] == resp2.json()["id"]

    def test_stock_deducted_only_once(self, client):
        make_product(client, sku="SKU-ONCE", stock=10)
        key = str(uuid.uuid4())
        payload = {"idempotency_key": key, "items": [
            {"sku": "SKU-ONCE", "quantity": 3}]}

        client.post("/orders", json=payload)
        client.post("/orders", json=payload)
        client.post("/orders", json=payload)

        stock = client.get("/products/SKU-ONCE").json()["stock"]
        assert stock == 7  # deducted exactly once

    def test_duplicate_skus_in_request_rejected(self, client):
        make_product(client, sku="SKU-DUP2", stock=10)
        resp = client.post("/orders", json={
            "idempotency_key": str(uuid.uuid4()),
            "items": [
                {"sku": "SKU-DUP2", "quantity": 1},
                {"sku": "SKU-DUP2", "quantity": 2},
            ],
        })
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# 5. Concurrency — the key test for this assignment
# ─────────────────────────────────────────────────────────────────────────────

class TestConcurrency:

    def test_only_one_order_succeeds_for_last_item(self, client):
        """
        10 threads simultaneously try to buy the only item in stock.
        Exactly 1 should succeed. Stock must never go below 0.
        PostgreSQL SELECT FOR UPDATE guarantees this.
        """
        make_product(client, sku="SKU-RACE", stock=1)

        results = []
        lock = threading.Lock()

        def try_buy():
            resp = client.post("/orders", json={
                "idempotency_key": str(uuid.uuid4()),
                "items": [{"sku": "SKU-RACE", "quantity": 1}],
            })
            with lock:
                results.append(resp.status_code)

        threads = [threading.Thread(target=try_buy) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        counts = Counter(results)
        successes = counts[201]
        failures = counts[409]

        assert successes == 1, f"Expected 1 success, got {successes}. Results: {counts}"
        assert failures == 9, f"Expected 9 failures, got {failures}. Results: {counts}"

        final_stock = client.get("/products/SKU-RACE").json()["stock"]
        assert final_stock == 0, f"Stock should be 0, got {final_stock}"
