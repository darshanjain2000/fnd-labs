"""Base class for DAL repositories.

Concrete DALs subclass ``BaseRepository`` and use ``_session()`` to open a
scoped SQLAlchemy session. Sessions are always closed automatically, even
on exception paths.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from app.db import SessionLocal


class BaseRepository:
    """Shared session management for DAL repositories.

    Subclasses call ``with self._session() as session:`` instead of opening
    sessions directly. The session factory is injected so tests can hand in
    an in-memory DB without patching module-level globals.
    """

    def __init__(self, session_factory: Callable[[], Session] = SessionLocal) -> None:
        """Initialise the repository.

        Args:
            session_factory: Callable returning a SQLAlchemy ``Session``.
                Defaults to the module-level ``SessionLocal``.
        """
        self._session_factory = session_factory

    @contextmanager
    def _session(self) -> Iterator[Session]:
        """Yield a scoped SQLAlchemy session that is always closed on exit."""
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()
