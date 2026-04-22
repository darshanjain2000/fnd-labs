from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.routers import deps

client = TestClient(app)


def _envelope(resp) -> dict:
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "statusCode" in body and "result" in body
    return body


def test_view_config_masks_secrets():
    body = _envelope(client.get("/config"))
    data = body["result"]
    assert body["statusCode"] == 200
    assert data["mode"] in ("paper", "live")
    assert data["broker"] in ("paper", "kite", "angel")
    assert "enabled_strategies" in data
    for k in ("openrouter_api_key", "kite_access_token", "angel_pin"):
        val = data.get(k, "")
        assert val in ("", "***set***")


def test_patch_config_applies_and_rebuilds():
    body = _envelope(
        client.patch("/config", json={"openrouter_enabled": False, "paper_trade": True})
    )
    assert body["statusCode"] == 200
    result = body["result"]
    assert result["applied"]["openrouter_enabled"] is False
    assert result["applied"]["paper_trade"] is True
    assert get_settings().openrouter_enabled is False


def test_patch_rejects_unknown_field():
    r = client.patch("/config", json={"nonsense": True})
    # Pydantic extra="forbid" returns 422 before the handler runs — validation layer.
    assert r.status_code == 422


def test_enabled_strategies_controls_signal_service():
    deps.reset_cached_singletons()
    body = _envelope(
        client.patch("/config", json={"enabled_strategies": "rsi_reversal"})
    )
    assert body["statusCode"] == 200
    service = deps.get_signal_service()
    names = [s.name for s in service.strategies]
    assert names == ["rsi_reversal"]


def test_validation_service_disabled_uses_fallback():
    from app.services.validation_service import ValidationService
    from app.strategies.base import Signal

    client.patch(
        "/config",
        json={"openrouter_enabled": False, "ai_fallback_approve_threshold": 0.6},
    )
    service = ValidationService()
    hi = Signal(symbol="X", strategy="t", side="BUY", entry=100, stop_loss=98, target=104, confidence=0.9)
    lo = Signal(symbol="X", strategy="t", side="BUY", entry=100, stop_loss=98, target=104, confidence=0.3)
    assert service.validate(hi).approved is True
    assert service.validate(lo).approved is False


def test_reload_endpoint():
    body = _envelope(client.post("/config/reload"))
    assert body["statusCode"] == 200 and body["result"]["reloaded"] is True
