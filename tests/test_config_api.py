from fastapi.testclient import TestClient

from app.api import deps
from app.config import get_settings
from app.main import app

client = TestClient(app)


def test_view_config_masks_secrets():
    r = client.get("/config")
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] in ("paper", "live")
    assert data["broker"] in ("paper", "kite", "angel")
    assert "enabled_strategies" in data
    # Secret fields must not leak their actual values in plaintext.
    for k in ("openrouter_api_key", "kite_access_token", "angel_pin"):
        val = data.get(k, "")
        assert val in ("", "***set***")


def test_patch_config_applies_and_rebuilds():
    r = client.patch("/config", json={"openrouter_enabled": False, "paper_trade": True})
    assert r.status_code == 200
    body = r.json()
    assert body["applied"]["openrouter_enabled"] is False
    assert body["applied"]["paper_trade"] is True
    assert get_settings().openrouter_enabled is False


def test_patch_rejects_unknown_field():
    r = client.patch("/config", json={"nonsense": True})
    assert r.status_code == 422  # pydantic extra=forbid


def test_enabled_strategies_controls_signal_agent():
    deps.reset_cached_singletons()
    r = client.patch("/config", json={"enabled_strategies": "rsi_reversal"})
    assert r.status_code == 200
    agent = deps.get_signal_agent()
    names = [s.name for s in agent.strategies]
    assert names == ["rsi_reversal"]


def test_validation_agent_disabled_uses_fallback():
    from app.agents.validation_agent import ValidationAgent
    from app.strategies.base import Signal

    # Disable OpenRouter via config.
    client.patch("/config", json={"openrouter_enabled": False, "ai_fallback_approve_threshold": 0.6})
    agent = ValidationAgent()
    hi = Signal(symbol="X", strategy="t", side="BUY", entry=100, stop_loss=98, target=104, confidence=0.9)
    lo = Signal(symbol="X", strategy="t", side="BUY", entry=100, stop_loss=98, target=104, confidence=0.3)
    assert agent.validate(hi).approved is True
    assert agent.validate(lo).approved is False


def test_reload_endpoint():
    r = client.post("/config/reload")
    assert r.status_code == 200
    assert r.json()["reloaded"] is True
