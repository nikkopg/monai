"""
Alembic environment for monai.

Reads DATABASE_URL from the environment (same var used by the app) and wires
Base.metadata so autogenerate sees all ORM models.

Env vars:
  DATABASE_URL  (default: postgresql+psycopg://monai:monai@localhost:5434/monai)
"""

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Import the project's declarative Base so autogenerate sees all registered models.
from backend.models import Base

config = context.config

# Interpret the config file for Python logging (suppressed if no config file).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate — must reference the same Base used in db.py.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no live DB connection required).

    Emits SQL to stdout; used for reviewing migration SQL before applying.
    """
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://monai:monai@localhost:5434/monai",
    )
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connected to a live DB).

    Reads DATABASE_URL from the environment and overrides alembic.ini
    sqlalchemy.url to avoid configparser % interpolation issues (Pitfall 3).
    Uses pool.NullPool so the connection is not held between migrations.
    """
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://monai:monai@localhost:5434/monai",
    )
    # configparser treats % as interpolation — escape any % in the URL (e.g. passwords)
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = db_url.replace("%", "%%")

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
