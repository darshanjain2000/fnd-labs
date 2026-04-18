from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["message"] == "trading-poc is running"


def test_health():
    r = client.get("/health")
    assert r.json() == {"status": "ok"}


def test_positions_endpoint():
    r = client.get("/positions")
    assert r.status_code == 200
    assert "open_positions" in r.json()


def test_manual_paper_trade():
    r = client.post(
        "/trade/manual",
        json={"symbol": "TEST", "side": "BUY", "qty": 10, "mock_quote": 150.0},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "COMPLETE"
    assert data["filled_qty"] == 10
    assert data["avg_price"] > 0
