from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base

_settings = get_settings()
_connect_args = {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}

engine = create_engine(_settings.database_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


# Columns added after the initial schema — when an existing SQLite DB is loaded,
# `create_all` won't add them. We patch on boot using ALTER TABLE. Safe + idempotent.
# Format: {table: [(column_name, column_ddl_type), ...]}
_SQLITE_ADDITIONS: dict[str, list[tuple[str, str]]] = {
    "signals": [
        ("ai_confidence", "FLOAT"),
        ("ai_source", "VARCHAR(16)"),
    ],
}


def _apply_sqlite_additions() -> None:
    """Add columns that were introduced after initial schema creation.

    Only runs against SQLite (safe to no-op elsewhere — production DBs should use Alembic).
    """
    if not _settings.database_url.startswith("sqlite"):
        return
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in _SQLITE_ADDITIONS.items():
            if not insp.has_table(table):
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _apply_sqlite_additions()


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
