"""Tests for the ``ApiResponse[T]`` envelope and FastAPI exception handlers."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.enums.exception_codes import CustomExceptionCodes
from app.exceptions.base import DomainException
from app.exceptions.domain import TradeNotFoundException
from app.models.api.response import ApiResponse


class _Payload(BaseModel):
    """Simple payload used to exercise generic serialization."""

    id: int
    name: str


# ---------------------------------------------------------------------------
# ApiResponse serialization
# ---------------------------------------------------------------------------


def test_ok_envelope_serialises_with_typed_result() -> None:
    """A success envelope carries statusCode + typed result, no error."""
    resp = ApiResponse[_Payload].ok(_Payload(id=1, name="foo"))
    dumped = resp.model_dump()
    assert dumped["statusCode"] == 200
    assert dumped["result"] == {"id": 1, "name": "foo"}
    assert dumped["error"] is None


def test_ok_envelope_supports_custom_status_and_message() -> None:
    """``ApiResponse.ok`` accepts override ``status_code`` and ``message``."""
    resp = ApiResponse[int].ok(42, status_code=201, message="created")
    dumped = resp.model_dump()
    assert dumped["statusCode"] == 201
    assert dumped["message"] == "created"
    assert dumped["result"] == 42


def test_from_exception_uses_error_code_and_message() -> None:
    """``ApiResponse.from_exception`` reads ``error_code`` and ``str(exc)``."""
    exc = TradeNotFoundException("trade 99 missing")
    resp = ApiResponse[None].from_exception(exc)
    dumped = resp.model_dump()
    assert dumped["statusCode"] == CustomExceptionCodes.TradeNotFound
    assert dumped["result"] is None
    assert dumped["error"] == "trade 99 missing"


def test_from_exception_falls_back_to_class_name_when_message_empty() -> None:
    """When the exception has no message, use the class name."""
    exc = TradeNotFoundException()
    resp = ApiResponse[None].from_exception(exc)
    assert resp.error == "TradeNotFoundException"


# ---------------------------------------------------------------------------
# FastAPI global exception handler (re-uses handlers from app.main)
# ---------------------------------------------------------------------------


@pytest.fixture
def handler_app() -> FastAPI:
    """A minimal FastAPI app that installs the same handlers as ``app.main``."""
    from fastapi import Request
    from fastapi.responses import JSONResponse

    app = FastAPI()

    @app.exception_handler(DomainException)
    async def _domain_handler(_req: Request, exc: DomainException) -> JSONResponse:
        return JSONResponse(content=ApiResponse.from_exception(exc).model_dump())

    @app.exception_handler(Exception)
    async def _unhandled(_req: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(
            status_code=500,
            content=ApiResponse(statusCode=500, result=None, error="Internal server error").model_dump(),
        )

    @app.get("/missing-trade")
    def _missing_trade() -> None:
        raise TradeNotFoundException("trade 7 not found")

    @app.get("/boom")
    def _boom() -> None:
        raise RuntimeError("totally unexpected")

    return app


def test_domain_exception_is_translated_to_envelope(handler_app: FastAPI) -> None:
    """Raising a ``DomainException`` in a route yields the ``ApiResponse`` shape."""
    client = TestClient(handler_app, raise_server_exceptions=False)
    r = client.get("/missing-trade")
    assert r.status_code == 200  # envelope is always wrapped in 200
    body = r.json()
    assert body["statusCode"] == CustomExceptionCodes.TradeNotFound
    assert body["error"] == "trade 7 not found"
    assert body["result"] is None


def test_unhandled_exception_returns_500_envelope(handler_app: FastAPI) -> None:
    """Unknown exceptions surface as a 500 envelope with a safe message."""
    client = TestClient(handler_app, raise_server_exceptions=False)
    r = client.get("/boom")
    assert r.status_code == 500
    body = r.json()
    assert body["statusCode"] == 500
    assert body["error"] == "Internal server error"
    assert body["result"] is None
