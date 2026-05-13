"""Audit-log list endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app.dal.audit_log_dal import AuditLogDAL
from app.models.api import ApiResponse, AuditLogListOut, AuditLogOut

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("", response_model=ApiResponse[AuditLogListOut])
def list_audit(limit: int = 50) -> ApiResponse[AuditLogListOut]:
    """List the most recent audit-log events, newest first."""
    rows = AuditLogDAL().list_recent(limit=limit)
    payload = AuditLogListOut(
        count=len(rows), logs=[AuditLogOut.from_row(r) for r in rows]
    )
    return ApiResponse[AuditLogListOut].ok(payload)
