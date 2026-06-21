# Phase 1: Schema Foundation + Auth - Pattern Map

**Mapped:** 2026-06-21
**Files analyzed:** 12 new/modified files
**Analogs found:** 10 / 12

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `alembic/env.py` | config | batch (DDL) | `backend/config.py` | role-match (env-var config pattern) |
| `alembic/versions/001_baseline.py` | migration | batch (DDL) | `backend/db.py` (schema bootstrap) | partial (same DDL intent) |
| `alembic/versions/002_new_tables.py` | migration | batch (DDL) | `backend/db.py` (schema bootstrap) | partial (same DDL intent) |
| `alembic.ini` | config | — | `backend/config.py` | partial (config file pattern) |
| `backend/auth.py` | middleware | request-response | `backend/db.py:get_session` (dependency) | role-match |
| `backend/db.py` (modify) | config/utility | request-response | `backend/db.py` | exact (self) |
| `backend/models.py` (modify) | model | CRUD | `backend/models.py` | exact (self) |
| `backend/schemas.py` (modify) | model | request-response | `backend/schemas.py` | exact (self) |
| `backend/main.py` (modify) | controller | request-response | `backend/main.py` | exact (self) |
| `backend/requirements.txt` (modify) | config | — | `backend/requirements.txt` | exact (self) |
| `backend/entrypoint.sh` | config | batch | `backend/Dockerfile` | partial (CMD pattern) |
| `ui/app/api/[...proxy]/route.ts` | middleware | request-response | `ui/next.config.js` (proxy pattern) | role-match |
| `backend/tests/test_auth.py` | test | request-response | `backend/tests/test_router.py` | role-match |
| `backend/tests/test_decimal.py` | test | request-response | `backend/tests/test_router.py` | role-match |

---

## Pattern Assignments

### `alembic/env.py` (config, batch/DDL)

**Analog:** `backend/config.py`

**Env-var read pattern** (`backend/config.py` lines 14-18):
```python
import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://monai:monai@localhost:5434/monai",
)
```

**Core env.py pattern** (from RESEARCH.md Pattern 2 — no existing analog in codebase, but follows `config.py` env-var convention):
```python
# alembic/env.py
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

from backend.models import Base           # import same Base used in db.py

config = context.config
fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_online():
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://monai:monai@localhost:5434/monai",
    )
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = db_url.replace("%", "%%")  # escape configparser %

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
```

**Key detail:** Use `postgresql+psycopg://` (psycopg3 sync) — the same scheme already in `DATABASE_URL`. Do NOT use the async Alembic env pattern.

---

### `alembic/versions/001_baseline.py` (migration, batch/DDL)

**Analog:** `backend/db.py` — the `_DATE_HELPERS_VIEW` SQL block and `Base.metadata.create_all()` are the pre-Alembic equivalent.

**Column type conventions from `backend/models.py`** (lines 16-58):
```python
# These exact column types must match what the live DB has.
# Copy them faithfully from models.py — do not invent types.
from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text

# accounts table (mirrors Account model lines 31-37):
sa.Column("id", sa.Integer, primary_key=True),
sa.Column("name", sa.String(255), nullable=False),  # unique=True, index=True
sa.Column("type", sa.String(64), nullable=True),
sa.Column("currency", sa.String(8), nullable=True),

# transactions table (mirrors Transaction model lines 44-58):
sa.Column("id", sa.Integer, primary_key=True),
sa.Column("date", sa.DateTime, nullable=False),       # index=True
sa.Column("amount", sa.Numeric(18, 2), nullable=False),
sa.Column("currency", sa.String(8), nullable=False),
sa.Column("category", sa.String(255), nullable=True),
sa.Column("raw_category", sa.String(255), nullable=True),
sa.Column("merchant", sa.String(512), nullable=True),
sa.Column("notes", sa.Text, nullable=True),
sa.Column("account_id", sa.Integer, sa.ForeignKey("accounts.id"), nullable=True),  # index=True
sa.Column("is_transfer", sa.Boolean, nullable=False),  # index=True
```

**Critical:** This migration is stamped, not run, on the live DB. The `upgrade()` body is for fresh DB setup only. Add this comment prominently at the top of `upgrade()`.

---

### `alembic/versions/002_new_tables.py` (migration, batch/DDL)

**Analog:** `backend/db.py` `_DATE_HELPERS_VIEW` string (lines 14-28) — the view SQL is lifted verbatim from here and placed into `op.execute()`.

**View SQL to migrate** (`backend/db.py` lines 14-28):
```python
_DATE_HELPERS_VIEW = """
CREATE OR REPLACE VIEW date_helpers AS SELECT
    date_trunc('month', now())::date                                      AS current_month_start,
    (date_trunc('month', now()) + interval '1 month - 1 day')::date       AS current_month_end,
    date_trunc('month', now() - interval '1 month')::date                 AS last_month_start,
    (date_trunc('month', now()) - interval '1 day')::date                 AS last_month_end,
    date_trunc('year', now())::date                                       AS current_year_start,
    (date_trunc('year', now()) + interval '3 month - 1 day')::date         AS q1_end,
    (date_trunc('year', now()) + interval '3 month')::date                 AS q2_start,
    (date_trunc('year', now()) + interval '6 month - 1 day')::date         AS q2_end,
    (date_trunc('year', now()) + interval '6 month')::date                 AS q3_start,
    (date_trunc('year', now()) + interval '9 month - 1 day')::date         AS q3_end,
    (date_trunc('year', now()) + interval '9 month')::date                 AS q4_start,
    (date_trunc('year', now()) + interval '12 month - 1 day')::date        AS q4_end;
"""
```

**Numeric precision decisions** (D-09):
```python
# money fields — consistent with transactions.amount:
sa.Column("avg_cost", sa.Numeric(18, 2), nullable=False)
sa.Column("price",    sa.Numeric(18, 2), nullable=False)

# quantity fields (crypto-standard):
sa.Column("quantity", sa.Numeric(28, 8), nullable=False)
```

**JSONB columns** (D-10) — use `sqlalchemy.dialects.postgresql.JSONB`:
```python
from sqlalchemy.dialects.postgresql import JSONB, UUID
sa.Column("before",   JSONB, nullable=True)
sa.Column("after",    JSONB, nullable=True)
sa.Column("payload",  JSONB, nullable=False)
```

**UUID primary key** (proposals table, D-11):
```python
import uuid
from sqlalchemy.dialects.postgresql import UUID
sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
sa.Column("token", sa.String(64), nullable=False, unique=True)  # separate high-entropy secret
```

---

### `backend/auth.py` (middleware/dependency, request-response)

**Analog:** `backend/db.py` `get_session()` (lines 38-44) — the canonical FastAPI dependency pattern in this codebase.

**FastAPI dependency pattern** (`backend/db.py` lines 38-44):
```python
def get_session():
    """FastAPI dependency — yields a session, always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

**How dependencies are consumed in routes** (`backend/main.py` lines 63, 68, 78):
```python
# Injected via Depends() in the function signature:
def list_accounts(db: Session = Depends(get_session)):
def create_transaction(payload: TransactionCreate, db: Session = Depends(get_session)):

# For auth, use the dependencies= parameter (return value not needed in handler body):
@app.post("/transactions", response_model=TransactionOut, status_code=201,
          dependencies=[Depends(require_api_key)])
```

**Env-var read pattern** (match `backend/config.py` lines 14-18 — module-level, not inside function):
```python
import os
_CONFIGURED_KEY: str = os.environ.get("MONAI_API_KEY", "")
```

**Module docstring pattern** (match `backend/config.py` lines 1-12):
```python
"""
Auth dependency for monai backend.

Env vars:
  MONAI_API_KEY    required for all write endpoints (POST /transactions, POST /import)
"""
```

**Full auth.py implementation:**
```python
import hmac
import os
from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

_API_KEY_HEADER = APIKeyHeader(name="MONAI_API_KEY", auto_error=False)
_CONFIGURED_KEY: str = os.environ.get("MONAI_API_KEY", "")


def require_api_key(api_key: str | None = Security(_API_KEY_HEADER)) -> None:
    """FastAPI dependency — attach to write routes only."""
    if not _CONFIGURED_KEY:
        raise RuntimeError("MONAI_API_KEY env var is not set — refusing all writes.")
    if not api_key or not hmac.compare_digest(api_key, _CONFIGURED_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
```

---

### `backend/db.py` (modify — remove `create_all` and view creation)

**Analog:** itself. Current file at `backend/db.py`.

**Lines to REMOVE** (`backend/db.py` lines 13-35):
```python
# DELETE this entire block (the _DATE_HELPERS_VIEW string + init_db function):
_DATE_HELPERS_VIEW = """..."""

def init_db() -> None:
    """Create tables and the date_helpers view if absent."""
    Base.metadata.create_all(engine)     # <-- remove: Alembic owns schema
    with engine.begin() as conn:
        conn.execute(text(_DATE_HELPERS_VIEW))  # <-- remove: moved to migration 002
```

**Import to REMOVE** (`backend/db.py` line 3):
```python
from sqlalchemy import create_engine, text  # remove `text` if unused after edit
```

**Lines to KEEP** (engine + session factory pattern):
```python
"""SQLAlchemy engine, session factory, and schema bootstrap."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import DATABASE_URL
from backend.models import Base

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session():
    """FastAPI dependency — yields a session, always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

---

### `backend/models.py` (modify — add 5 new ORM models, fix Transaction.amount annotation)

**Analog:** itself. Current `Account` and `Transaction` models (`backend/models.py` lines 27-62) are the pattern to replicate.

**Existing model pattern** (`backend/models.py` lines 31-41, 44-62):
```python
class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="account"
    )
```

**Annotation fix** (`backend/models.py` line 49):
```python
# BEFORE (wrong — Python type hint says float but DB is Numeric):
amount: Mapped[float] = mapped_column(Numeric(18, 2))

# AFTER (correct — Python type matches DB Numeric return):
amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
# Requires: from decimal import Decimal  (add to imports at top of models.py)
```

**New imports to add** (`backend/models.py`):
```python
from datetime import datetime, date   # date needed for holdings.purchase_date, portfolio_events.date
from decimal import Decimal           # needed for Mapped[Decimal] annotation
from sqlalchemy.dialects.postgresql import JSONB
```

**New model stubs** (follow existing `Account`/`Transaction` style — SQLAlchemy 2.0 `Mapped[]` annotations):
```python
class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    # ... Mapped[str], Mapped[int | None], Mapped[dict | None] for JSONB ...

class Proposal(Base):
    __tablename__ = "proposals"
    # id: UUID primary key — use sa.Uuid or String(36); token: Mapped[str]

class Holding(Base):
    __tablename__ = "holdings"
    # quantity: Mapped[Decimal] = mapped_column(Numeric(28, 8))
    # avg_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2))

class PortfolioEvent(Base):
    __tablename__ = "portfolio_events"

class PriceCache(Base):
    __tablename__ = "price_cache"
```

---

### `backend/schemas.py` (modify — add `MoneyDecimal`, fix `amount: float`)

**Analog:** itself. Current schemas (`backend/schemas.py` lines 1-57).

**Existing schema pattern** (`backend/schemas.py` lines 8-31):
```python
class TransactionCreate(BaseModel):
    date: datetime
    amount: float = Field(..., description="Signed: negative = expense, positive = income")
    currency: str = "IDR"
    ...

class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)   # ORM mode
    id: int
    amount: float
    ...
```

**New imports to add** (top of `backend/schemas.py`):
```python
from decimal import Decimal
from typing import Annotated
from pydantic import PlainSerializer
```

**MoneyDecimal alias to add** (after imports, before first class):
```python
# Shared money type: validates as Decimal, serializes as JSON number (not string).
# Use for all amount/price/quantity fields across all schemas.
MoneyDecimal = Annotated[
    Decimal,
    PlainSerializer(lambda x: float(x), return_type=float, when_used="json"),
]
```

**Fields to change** (`backend/schemas.py` lines 10, 22):
```python
# TransactionCreate line 10 — BEFORE:
amount: float = Field(..., description="Signed: negative = expense, positive = income")
# AFTER:
amount: MoneyDecimal = Field(..., description="Signed: negative = expense, positive = income")

# TransactionOut line 22 — BEFORE:
amount: float
# AFTER:
amount: MoneyDecimal
```

**New schemas to add** (follow existing `*Create`/`*Out` naming and `ConfigDict(from_attributes=True)` for ORM reads):
```python
# No new schemas needed in Phase 1 for the 5 new tables —
# those tables are created but consumed in Phase 2/5.
# Only the Decimal retrofit and MoneyDecimal alias are in scope here.
```

---

### `backend/main.py` (modify — add auth dependency on write routes, remove `init_db` startup)

**Analog:** itself. Current imports and route definitions (`backend/main.py` lines 1-124).

**Import to ADD** (`backend/main.py` after line 23):
```python
from backend.auth import require_api_key
```

**Import to REMOVE** (`backend/main.py` line 24):
```python
from backend.db import get_session, init_db   # remove init_db
```

**Startup hook to REMOVE** (`backend/main.py` lines 52-54):
```python
# DELETE entire startup event (Alembic owns schema now):
@app.on_event("startup")
def _startup():
    init_db()
```

**Write routes to modify** — add `dependencies=[Depends(require_api_key)]`:
```python
# POST /transactions — currently line 77:
@app.post("/transactions", response_model=TransactionOut, status_code=201,
          dependencies=[Depends(require_api_key)])
def create_transaction(payload: TransactionCreate, db: Session = Depends(get_session)):
    ...

# POST /import — currently line 100:
@app.post("/import", response_model=ImportResponse,
          dependencies=[Depends(require_api_key)])
async def import_csv(file: UploadFile = File(...), db: Session = Depends(get_session)):
    ...

# POST /query — NO dependency (D-06: read-only despite being POST):
@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    ...
```

**GET routes — no change needed** (stay fully public per D-06).

---

### `backend/entrypoint.sh` (config, batch)

**Analog:** `backend/Dockerfile` CMD (line 16).

**Current CMD pattern** (`backend/Dockerfile` line 16):
```dockerfile
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

**Entrypoint pattern** (wraps CMD with migration step first):
```bash
#!/bin/sh
set -e
echo "[monai] Running database migrations..."
alembic upgrade head
echo "[monai] Starting backend..."
exec uvicorn backend.main:app --host 0.0.0.0 --port 8001
```

**Dockerfile change** — replace CMD with:
```dockerfile
COPY backend/entrypoint.sh ./backend/entrypoint.sh
RUN chmod +x backend/entrypoint.sh
CMD ["./backend/entrypoint.sh"]
```

---

### `ui/app/api/[...proxy]/route.ts` (middleware, request-response)

**Analog:** `ui/next.config.js` lines 4-7 — the existing rewrite proxy that this replaces.

**Existing proxy pattern** (`ui/next.config.js` lines 4-7):
```javascript
async rewrites() {
  const backend = process.env.MONAI_API || "http://127.0.0.1:8001";
  return [{ source: "/api/:path*", destination: `${backend}/:path*` }];
},
```

**Existing client fetch pattern** (`ui/app/page.tsx` lines 63-65, 76-80, 103-107):
```typescript
// GET — no special headers needed:
const r = await fetch("/api/transactions?limit=10");

// POST — Content-Type only, no explicit API key (injected by proxy):
const r = await fetch("/api/query", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ question }),
});
```

**TypeScript conventions** (`ui/app/page.tsx` lines 1, 4-12):
```typescript
"use client";  // only for client components — route handler does NOT need this
import { NextRequest, NextResponse } from "next/server";
// camelCase functions, PascalCase types
// async handlers throughout
```

**Full route handler pattern** (no `"use client"` — this is a server-side route):
```typescript
// ui/app/api/[...proxy]/route.ts
import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.MONAI_API || "http://127.0.0.1:8001";
const API_KEY = process.env.MONAI_API_KEY || "";

async function forwardRequest(
  req: NextRequest,
  segments: string[]
): Promise<NextResponse> {
  const path = segments.join("/");
  const url = new URL(req.url);
  const target = `${BACKEND}/${path}${url.search}`;

  const headers = new Headers(req.headers);
  headers.set("MONAI_API_KEY", API_KEY);
  headers.delete("host");  // avoid confusing the upstream

  const init: RequestInit = { method: req.method, headers };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.arrayBuffer();
  }

  const upstream = await fetch(target, init);
  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: upstream.headers,
  });
}

export async function GET(
  req: NextRequest,
  { params }: { params: { proxy: string[] } }
) {
  return forwardRequest(req, params.proxy);
}

export async function POST(
  req: NextRequest,
  { params }: { params: { proxy: string[] } }
) {
  return forwardRequest(req, params.proxy);
}
```

**next.config.js change:** Remove the `rewrites()` block entirely (or leave it as a no-op) since the route handler takes over `/api/*`.

---

### `backend/tests/test_auth.py` (test, request-response)

**Analog:** `backend/tests/test_router.py` — same module structure, pytest style, no class wrapper for simple cases.

**Test file pattern** (`backend/tests/test_router.py` lines 1-6):
```python
"""Router JSON extraction — pure, no LLM or DB needed."""

import pytest

from backend.query import _extract_json
```

**Test pattern** — plain functions, `pytest.raises` for error cases:
```python
def test_plain_json():
    assert _extract_json('{"tool": "spending_total", ...}') == {...}

def test_no_json_raises():
    with pytest.raises(ValueError):
        _extract_json("I have no idea how to answer that.")
```

**test_auth.py structure** (uses `TestClient` from `fastapi.testclient`):
```python
"""API key authentication — unit tests (no DB required)."""

import os
import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_write_without_key_returns_401(monkeypatch):
    monkeypatch.setenv("MONAI_API_KEY", "test-secret-key")
    r = client.post("/transactions", json={...})
    assert r.status_code == 401

def test_write_with_valid_key_passes(monkeypatch):
    monkeypatch.setenv("MONAI_API_KEY", "test-secret-key")
    r = client.post("/transactions",
                    json={...},
                    headers={"MONAI_API_KEY": "test-secret-key"})
    # 201 or 422 (validation) — not 401
    assert r.status_code != 401

def test_get_is_public():
    r = client.get("/accounts")
    assert r.status_code == 200

def test_query_is_public():
    # POST /query stays public (D-06)
    r = client.post("/query", json={"question": "test"})
    assert r.status_code != 401
```

---

### `backend/tests/test_decimal.py` (test, request-response)

**Analog:** `backend/tests/test_router.py` — same file structure.

**Pattern for Decimal round-trip test:**
```python
"""Decimal serialization — Pydantic v2 round-trip tests (no DB required)."""

from decimal import Decimal
from backend.schemas import TransactionCreate, TransactionOut, MoneyDecimal


def test_money_decimal_serializes_as_number():
    """MoneyDecimal must produce a JSON number, not a string."""
    import json
    from pydantic import BaseModel

    class _M(BaseModel):
        amount: MoneyDecimal

    m = _M(amount=Decimal("123456.78"))
    payload = json.loads(m.model_dump_json())
    assert isinstance(payload["amount"], float)  # not str
    assert payload["amount"] == 123456.78


def test_transaction_create_accepts_decimal():
    tx = TransactionCreate(
        date="2026-01-01T00:00:00",
        amount=Decimal("-25000.00"),
        account="Cash",
    )
    assert tx.amount == Decimal("-25000.00")
```

---

## Shared Patterns

### FastAPI Dependency Injection
**Source:** `backend/db.py` lines 38-44 and `backend/main.py` lines 63, 68, 78
**Apply to:** `backend/auth.py` (new dependency), all modified route signatures
```python
# Dependency definition pattern (db.py):
def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Usage pattern — in-signature (for values consumed by handler):
def list_accounts(db: Session = Depends(get_session)):

# Usage pattern — declarative (for side-effect-only deps like auth):
@app.post("/transactions", dependencies=[Depends(require_api_key)])
```

### Env-Var Config
**Source:** `backend/config.py` lines 14-18
**Apply to:** `alembic/env.py`, `backend/auth.py`
```python
import os

# Module-level read with default:
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://monai:monai@localhost:5434/monai",
)

# No dotenv — pure 12-factor env var reading
```

### Error Handling (API layer)
**Source:** `backend/main.py` lines 104-112
**Apply to:** Any new route handlers added in future phases
```python
# ValueError from domain → 422; generic Exception caught at route level:
try:
    parsed, inserted, skipped, currency = import_csv_text(db, text_content)
except ValueError as e:
    raise HTTPException(422, str(e))
```

### SQLAlchemy 2.0 ORM Model Style
**Source:** `backend/models.py` lines 27-62
**Apply to:** All 5 new ORM models in `backend/models.py`
```python
class Account(Base):
    __tablename__ = "accounts"      # explicit table name

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Rule: Mapped[T] annotation must match actual Python type returned by DB
    # Rule: nullable columns → Mapped[T | None]
```

### Pydantic v2 Schema Style
**Source:** `backend/schemas.py` lines 8-57
**Apply to:** `MoneyDecimal` alias and any new `*Create`/`*Out` schemas
```python
# Input schemas: no ConfigDict needed
class TransactionCreate(BaseModel):
    date: datetime
    amount: float = Field(..., description="...")

# Output/ORM schemas: ConfigDict(from_attributes=True) required
class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ...
```

### Module Docstring Convention
**Source:** `backend/models.py` lines 1-12, `backend/config.py` lines 1-12
**Apply to:** All new backend Python files
```python
"""
One-line summary of what this module does.

Multi-line explanation of key decisions or env vars if relevant.
"""
```

### TypeScript Component Pattern
**Source:** `ui/app/page.tsx` lines 1-12, `ui/app/layout.tsx`
**Apply to:** `ui/app/api/[...proxy]/route.ts`
```typescript
// Server route handlers: NO "use client" directive
// Client components: "use client" at top

// camelCase for functions/state:
async function forwardRequest(...) { ... }

// PascalCase for types:
type Tx = { id: number; ... }
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `alembic.ini` | config | — | No INI-format config files in this codebase; follow Alembic default template with `sqlalchemy.url` left as placeholder (overridden in `env.py`) |
| `backend/entrypoint.sh` | config/utility | batch | No shell scripts in codebase; Dockerfile CMD is the nearest intent analog |

---

## Metadata

**Analog search scope:** `backend/`, `ui/app/`, `ui/next.config.js`
**Files scanned:** 11 source files read directly
**Pattern extraction date:** 2026-06-21

**Critical reminders for planner:**
- `backend/models.py:49` — change `Mapped[float]` to `Mapped[Decimal]` on `Transaction.amount`
- `backend/schemas.py:10,22` — change `amount: float` to `amount: MoneyDecimal` in both `TransactionCreate` and `TransactionOut`
- `backend/db.py:31-35` — delete `init_db()` entirely; also delete the `_DATE_HELPERS_VIEW` string (lines 14-28) and the `text` import if no longer used
- `backend/main.py:52-54` — delete the `@app.on_event("startup")` block; remove `init_db` from the `from backend.db import ...` line
- `ui/next.config.js:4-7` — `rewrites()` block becomes redundant once route handler is in place; remove to avoid double-routing
- `alembic stamp <001_rev>` must run **before** `alembic upgrade head` on the live DB — enforce in runbook
