"""Unit tests for ``AuditLogDAL``."""
from __future__ import annotations

from datetime import datetime

from app.dal.audit_log_dal import AuditLogDAL
from app.models.trade import AuditLog


def test_list_recent_orders_newest_first(db_factory) -> None:
    factory = db_factory()
    with factory() as s:
        s.add_all(
            [
                AuditLog(at=datetime(2026, 1, 1), event="older", payload={"k": 1}),
                AuditLog(at=datetime(2026, 4, 1), event="newer", payload={"k": 2}),
            ]
        )
        s.commit()

    rows = AuditLogDAL(session_factory=factory).list_recent()
    assert [r.event for r in rows] == ["newer", "older"]


def test_list_recent_applies_limit(db_factory) -> None:
    factory = db_factory()
    with factory() as s:
        s.add_all([AuditLog(event=f"evt-{i}", payload={}) for i in range(5)])
        s.commit()

    rows = AuditLogDAL(session_factory=factory).list_recent(limit=3)
    assert len(rows) == 3
