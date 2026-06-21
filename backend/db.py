"""SQLAlchemy engine, session factory, and FastAPI dependency.

Schema is fully Alembic-managed after Phase 1. The former init_db() function
and the _DATE_HELPERS_VIEW SQL string have been removed — schema bootstrap now
happens via `alembic upgrade head` in the Docker entrypoint (D-04, D-02).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import DATABASE_URL
from backend.models import Base  # noqa: F401 — keeps Base importable from db for legacy compat

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session():
    """FastAPI dependency — yields a session, always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
