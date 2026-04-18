"""Unit tests for AngelBroker — uses a fake SmartConnect so no live creds needed."""
from __future__ import annotations

import pytest

from app.config import reload_settings
from app.services.broker.angel_client import AngelBroker
from app.services.broker.base import OrderRequest


class FakeSmart:
    """Stand-in for SmartConnect. Records calls so tests can assert on them."""

    def __init__(self) -> None:
        self.placed: list[dict] = []
        self.cancelled: list[str] = []

    def searchScrip(self, exchange: str, searchtext: str):
        return {"status": True, "data": [{"symboltoken": "99999", "tradingsymbol": searchtext}]}

    def placeOrder(self, params: dict):
        self.placed.append(params)
        return "ANGEL-ORDER-1"

    def cancelOrder(self, order_id: str, variety: str = "NORMAL"):
        self.cancelled.append(order_id)
        return {"status": True}

    def ltpData(self, exchange: str, symbol: str, token: str):
        return {"data": {"ltp": 123.45}}

    def getProfile(self, refreshToken=None):
        return {"status": True, "data": {"clientcode": "TEST123"}}


@pytest.fixture
def angel(monkeypatch):
    # Populate required settings so the constructor doesn't bail early.
    monkeypatch.setenv("ANGEL_API_KEY", "k")
    monkeypatch.setenv("ANGEL_CLIENT_CODE", "TEST123")
    monkeypatch.setenv("ANGEL_PIN", "1234")
    monkeypatch.setenv("ANGEL_TOTP_SECRET", "JBSWY3DPEHPK3PXP")
    reload_settings()
    fake = FakeSmart()
    return AngelBroker(smart_connect=fake), fake


def test_angel_requires_credentials(monkeypatch):
    for k in ("ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PIN", "ANGEL_TOTP_SECRET"):
        monkeypatch.delenv(k, raising=False)
    reload_settings()
    with pytest.raises(RuntimeError, match="Angel credentials missing"):
        AngelBroker(smart_connect=FakeSmart())


def test_place_market_order_resolves_token_and_formats_params(angel):
    broker, fake = angel
    result = broker.place_order(OrderRequest(symbol="NIFTY25APR22500CE", side="BUY", qty=50))
    assert result.order_id == "ANGEL-ORDER-1"
    assert result.status == "OPEN"
    assert len(fake.placed) == 1
    p = fake.placed[0]
    assert p["symboltoken"] == "99999"
    assert p["variety"] == "NORMAL"
    assert p["ordertype"] == "MARKET"
    assert p["producttype"] == "INTRADAY"
    assert p["transactiontype"] == "BUY"
    assert p["quantity"] == "50"


def test_place_sl_m_order_uses_stoploss_variety(angel):
    broker, fake = angel
    broker.place_order(
        OrderRequest(symbol="X", side="SELL", qty=25, order_type="SL-M", trigger_price=100.5)
    )
    p = fake.placed[0]
    assert p["variety"] == "STOPLOSS"
    assert p["ordertype"] == "STOPLOSS_MARKET"
    assert p["triggerprice"] == "100.5"


def test_token_cache_avoids_duplicate_lookups(angel):
    broker, fake = angel
    calls = {"n": 0}
    original = fake.searchScrip

    def counting(exchange, searchtext):
        calls["n"] += 1
        return original(exchange, searchtext)

    fake.searchScrip = counting  # type: ignore[assignment]
    broker.resolve_token("ABC")
    broker.resolve_token("ABC")
    broker.resolve_token("ABC")
    assert calls["n"] == 1


def test_get_quote(angel):
    broker, _ = angel
    assert broker.get_quote("ANYSYM") == 123.45


def test_cancel_order(angel):
    broker, fake = angel
    assert broker.cancel_order("ANGEL-ORDER-1") is True
    assert fake.cancelled == ["ANGEL-ORDER-1"]


def test_order_failure_returns_rejected(angel, monkeypatch):
    broker, fake = angel

    def boom(params):
        raise RuntimeError("exchange closed")

    monkeypatch.setattr(fake, "placeOrder", boom)
    result = broker.place_order(OrderRequest(symbol="X", side="BUY", qty=50))
    assert result.status == "REJECTED"
    assert "exchange closed" in result.message


def test_profile_probe_ok(angel):
    broker, _ = angel
    p = broker.profile()
    assert p["ok"] is True
    assert p["client_code"] == "TEST123"
