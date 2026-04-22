from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _envelope(resp) -> dict:
    """Return the parsed ``ApiResponse`` envelope from a TestClient response."""
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "statusCode" in body and "result" in body and "error" in body
    return body


def test_root():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["message"] == "trading-poc is running"


def test_health():
    r = client.get("/health")
    assert r.json() == {"status": "ok"}


def test_positions_endpoint():
    body = _envelope(client.get("/admin/positions"))
    assert body["statusCode"] == 200 and body["error"] is None
    assert "open_positions" in body["result"]


def test_manual_paper_trade():
    body = _envelope(
        client.post(
            "/trade/manual",
            json={"symbol": "TEST", "side": "BUY", "qty": 10, "mock_quote": 150.0},
        )
    )
    assert body["statusCode"] == 200
    result = body["result"]
    assert result["status"] == "COMPLETE"
    assert result["filled_qty"] == 10
    assert result["avg_price"] > 0
