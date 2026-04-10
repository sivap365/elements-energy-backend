# Elements Energy — Backend Assignment

> Inventory-safe order management API built with **FastAPI + PostgreSQL**.  
> Guarantees stock correctness under concurrent requests, duplicate submissions, and server restarts.

---

## Tech Stack

- **Python 3.10+** — Language
- **FastAPI** — Web framework
- **PostgreSQL 15** — Database (via Docker)
- **SQLAlchemy** — ORM
- **Docker Desktop** — Container for PostgreSQL

---

## The Problem This Solves

An online store where:
- Products have limited stock
- Many users can try to buy the same product at the same time
- The system must **never sell more than available stock**

### Three hard guarantees:
| Challenge | Solution |
|---|---|
| Two users buy last item simultaneously | `SELECT ... FOR UPDATE` row-level lock — only one wins |
| Same request sent twice | `idempotency_key` unique constraint — stock deducted once |
| Code bug tries to make stock negative | `CHECK (stock >= 0)` DB constraint — PostgreSQL rejects it |

---

## Project Structure

```
elements_energy/
├── docker-compose.yml          # PostgreSQL container setup
├── requirements.txt            # Python dependencies
├── .env                        # Database URL (not committed)
├── app/
│   ├── main.py                 # FastAPI app entry point
│   ├── api/
│   │   ├── products.py         # POST /products, GET /products/{sku}
│   │   └── orders.py           # POST /orders, GET /orders/{id}
│   ├── db/
│   │   └── database.py         # DB engine and session
│   ├── models/
│   │   └── models.py           # 4 database tables (ORM)
│   ├── schemas/
│   │   └── schemas.py          # Request/response validation
│   └── services/
│       └── order_service.py    # Core business logic + locking
└── tests/
    └── test_api.py             # 17 tests (unit + concurrency)
```

---

## Database Design (4 tables)

| Table | Purpose | Key Constraint |
|---|---|---|
| `products` | Stock source of truth | `CHECK (stock >= 0)` |
| `orders` | Immutable order header | `UNIQUE (idempotency_key)` |
| `order_items` | Line items per order | `CHECK (quantity > 0)` |
| `idempotency_keys` | Deduplication store | `UNIQUE (key)` |

---

## APIs

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/products` | Create a product with stock |
| `GET` | `/products/{sku}` | Get product and current stock |
| `POST` | `/orders` | Place an order (idempotent) |
| `GET` | `/orders/{id}` | Get an order by ID |

---

## Setup & Run (Step by Step)

### Prerequisites
- [Python 3.10+](https://www.python.org/downloads/)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (must be running)

### Step 1 — Clone the repository
```bash
git clone https://github.com/sivap365/elements-energy-backend.git
cd elements-energy-backend
```

### Step 2 — Create virtual environment
```bash
python -m venv venv
venv\Scripts\activate
```

### Step 3 — Install dependencies
```bash
pip install -r requirements.txt
```

### Step 4 — Create the `.env` file
Create a file named `.env` in the root folder with this content:
```
DATABASE_URL=postgresql://elements:elements_pass@127.0.0.1:5433/elements_energy
```

### Step 5 — Start PostgreSQL with Docker
```bash
docker-compose up -d
```

### Step 6 — Start the server
```bash
uvicorn app.main:app --reload
```

Server is now running at **http://localhost:8000**

### Step 7 — Open API docs
Go to **http://localhost:8000/docs** in your browser.  
You'll see the full interactive Swagger UI to test all endpoints.

---

## Testing the APIs (in order)

### 1. Create a product
```json
POST /products
{
  "sku": "SKU-1",
  "name": "Widget Pro",
  "stock": 5
}
```
Expected: `201 Created`

### 2. Place an order
```json
POST /orders
{
  "idempotency_key": "order-001",
  "items": [{ "sku": "SKU-1", "quantity": 2 }]
}
```
Expected: `201 Created` — stock reduces from 5 to 3

### 3. Send same order again (idempotency test)
Send the exact same request again with `"idempotency_key": "order-001"`.  
Expected: `200 OK` — same order returned, stock still 3 (not reduced again)

### 4. Try to oversell (stock protection test)
```json
POST /orders
{
  "idempotency_key": "order-002",
  "items": [{ "sku": "SKU-1", "quantity": 99 }]
}
```
Expected: `409 Conflict` — "Insufficient stock"

---

## Running Automated Tests

```bash
python -m pytest tests/ -v
```

### Test Results
```
17 passed in 5.11s
```

| Test Category | Tests | Result |
|---|---|---|
| Product endpoints | 5 tests | ✅ All passed |
| Order happy path | 4 tests | ✅ All passed |
| Stock exhaustion | 4 tests | ✅ All passed |
| Idempotency | 3 tests | ✅ All passed |
| Concurrency | 1 test | ✅ Passed — 10 threads, 1 winner |

The **concurrency test** is the most important — it spawns 10 threads simultaneously trying to buy the last item in stock. Exactly 1 succeeds, 9 fail, and stock ends at exactly 0.

---

## Stopping the Server

```bash
# Press Ctrl+C to stop uvicorn

# Stop the database
docker-compose down
```

## Restarting Next Time

```bash
docker-compose up -d
venv\Scripts\activate
uvicorn app.main:app --reload
```

---

## How Concurrency Safety Works

```
Request arrives
      │
      ▼
Lock product row (SELECT ... FOR UPDATE)
      │   ← Only ONE transaction holds this lock at a time
      ▼
Check stock AFTER lock (not before)
      │
      ▼
Deduct stock + create order (same transaction)
      │
      ▼
Commit → release lock
```

Checking stock **after** acquiring the lock is critical. Checking before the lock is a race condition — another transaction could drain stock between the check and the update.

---

*Built with FastAPI + PostgreSQL | Python 100%*