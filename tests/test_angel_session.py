"""Tests for AngelSession — no live creds needed, uses FakeSmart."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from app.config import reload_settings
from app.services.angel_session import AngelSession


class FakeSmart:
    def generateSession(self, client, pin, totp):
        return {"status": True}

    def searchScrip(self, exchange, searchtext):
        return {"data": [{"symboltoken": "99926004"}]}

    def getCandleData(self, params):
        # Return 5 fake bars
        rows = []
        for i in range(5):
            rows.append([f"2026-04-18 09:{15 + i}:00", 100 + i, 102 + i, 99 + i, 101 + i, 1000 + i * 100])
        return {"status": True, "data": rows}


@pytest.fixture
def sess(monkeypatch):
    monkeypatch.setenv("ANGEL_API_KEY", "k")
    monkeypatch.setenv("ANGEL_CLIENT_CODE", "TEST")
    monkeypatch.setenv("ANGEL_PIN", "1234")
    monkeypatch.setenv("ANGEL_TOTP_SECRET", "JBSWY3DPEHPK3PXP")
    reload_settings()
    s = AngelSession()
    s._api = FakeSmart()  # inject directly, skip real login
    return s


def test_resolve_token_caches(sess):
    t1 = sess.resolve_token("NFO", "NIFTY25APR22500CE")
    t2 = sess.resolve_token("NFO", "NIFTY25APR22500CE")
    assert t1 == "99926004"
    assert t1 == t2


def test_candles_returns_dataframe(sess):
    df = sess.candles("NFO", "99926004", "5m", datetime(2026, 4, 18, 9, 15), datetime(2026, 4, 18, 15, 30))
    assert isinstance(df, pd.DataFrame)
    assert set(df.columns) >= {"open", "high", "low", "close", "volume", "datetime"}
    assert len(df) == 5


def test_missing_credentials_raises(monkeypatch):
    for k in ("ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PIN", "ANGEL_TOTP_SECRET"):
        monkeypatch.setenv(k, "")
    reload_settings()
    s = AngelSession()
    with pytest.raises(RuntimeError, match="Angel credentials not set"):
        s._ensure_logged_in()


def test_reset_clears_session(sess):
    sess.reset()
    assert sess._api is None
    assert sess._token_cache == {}
