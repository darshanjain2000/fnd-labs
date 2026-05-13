"""Tests for app.core.optimized_params — per-symbol parameter loader."""

from __future__ import annotations

from pathlib import Path


from app.core.optimized_params import load_params_for_symbol, params_file_for


def test_params_file_for_returns_expected_path(tmp_path: Path, monkeypatch) -> None:
    """params_file_for() should return config/params_{symbol_lower}.yaml."""
    import app.core.optimized_params as mod

    monkeypatch.setattr(mod, "_CONFIG_DIR", tmp_path)
    result = params_file_for("NIFTY")
    assert result == tmp_path / "params_nifty.yaml"


def test_load_params_returns_empty_when_no_file(tmp_path: Path, monkeypatch) -> None:
    """load_params_for_symbol() returns {} when no YAML file exists."""
    import app.core.optimized_params as mod

    monkeypatch.setattr(mod, "_CONFIG_DIR", tmp_path)
    result = load_params_for_symbol("UNKNOWN")
    assert result == {}


def test_load_params_parses_best_params_dict(tmp_path: Path, monkeypatch) -> None:
    """load_params_for_symbol() extracts best_params from a list-format YAML."""
    import yaml

    import app.core.optimized_params as mod

    monkeypatch.setattr(mod, "_CONFIG_DIR", tmp_path)

    data = {
        "rsi_reversal": {
            "best_params": {"atr_mult": 1.8, "oversold": 28.0, "overbought": 72.0},
            "best_value": 14.2,
            "metric": "sortino",
        },
        "ema_breakout": {
            "best_params": {"atr_mult": 1.2},
            "best_value": 9.7,
            "metric": "sortino",
        },
    }
    yaml_path = tmp_path / "params_nifty.yaml"
    with yaml_path.open("w") as fh:
        yaml.dump(data, fh)

    result = load_params_for_symbol("NIFTY")

    assert result["rsi_reversal"] == {
        "atr_mult": 1.8,
        "oversold": 28.0,
        "overbought": 72.0,
    }
    assert result["ema_breakout"] == {"atr_mult": 1.2}


def test_load_params_strips_metadata_keys(tmp_path: Path, monkeypatch) -> None:
    """Metadata keys (best_value, metric, strategy) are not included in returned params."""
    import yaml

    import app.core.optimized_params as mod

    monkeypatch.setattr(mod, "_CONFIG_DIR", tmp_path)

    data = {
        "rsi_reversal": {
            "best_params": {"atr_mult": 2.0},
            "best_value": 5.0,
            "metric": "sortino",
            "strategy": "rsi_reversal",
        }
    }
    yaml_path = tmp_path / "params_test.yaml"
    with yaml_path.open("w") as fh:
        yaml.dump(data, fh)

    result = load_params_for_symbol("TEST")
    assert "best_value" not in result["rsi_reversal"]
    assert "metric" not in result["rsi_reversal"]
    assert result["rsi_reversal"] == {"atr_mult": 2.0}


def test_load_params_returns_empty_on_corrupt_file(tmp_path: Path, monkeypatch) -> None:
    """load_params_for_symbol() returns {} gracefully if the YAML is corrupt."""
    import app.core.optimized_params as mod

    monkeypatch.setattr(mod, "_CONFIG_DIR", tmp_path)

    yaml_path = tmp_path / "params_bad.yaml"
    yaml_path.write_text(":: not valid yaml :::\n[broken")

    result = load_params_for_symbol("BAD")
    assert result == {}
