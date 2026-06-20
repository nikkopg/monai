"""SQLAlchemy engine, session factory, and schema bootstrap."""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.config import DATABASE_URL
from backend.models import Base

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# Postgres equivalent of the PoC's date_helpers view. The AI query layer
# references this for reliable relative-date queries ("last month", "this year").
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


def init_db() -> None:
    """Create tables and the date_helpers view if absent."""
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(_DATE_HELPERS_VIEW))


def get_session():
    """FastAPI dependency — yields a session, always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
