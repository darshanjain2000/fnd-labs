"""Unit tests for :class:`app.services.validation_service.ValidationService`."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.exceptions.domain import SpendCapExceededException
from app.services.validation_service import Validation, ValidationService
from app.strategies.base import Signal


class _FakeLLM:
    """Minimal :class:`LLMClient` replacement for deterministic tests."""

    def __init__(
        self, *, result: dict | None = None, raises: Exception | None = None
    ) -> None:
        self._result = result
        self._raises = raises
        self.calls: list[tuple[str, str, str]] = []

    def chat_json(self, system: str, user: str, schema_hint: str) -> dict | None:
        self.calls.append((system, user, schema_hint))
        if self._raises is not None:
            raise self._raises
        return self._result


def _signal(confidence: float = 0.7) -> Signal:
    return Signal(
        symbol="NIFTY",
        strategy="rsi_reversal",
        side="BUY",
        entry=100.0,
        stop_loss=98.0,
        target=104.0,
        confidence=confidence,
    )


@pytest.fixture
def _disable_llm(make_settings):
    with patch(
        "app.services.validation_service.get_settings",
        return_value=make_settings(
            openrouter_enabled=False, ai_fallback_approve_threshold=0.6
        ),
    ):
        yield


@pytest.fixture
def _enable_llm(make_settings):
    with patch(
        "app.services.validation_service.get_settings",
        return_value=make_settings(
            openrouter_enabled=True, ai_fallback_approve_threshold=0.6
        ),
    ):
        yield


def test_disabled_llm_falls_back_to_confidence_threshold(_disable_llm) -> None:
    svc = ValidationService(llm=_FakeLLM())
    approved = svc.validate(_signal(confidence=0.7))
    rejected = svc.validate(_signal(confidence=0.4))
    assert approved.approved is True and approved.source == "disabled"
    assert rejected.approved is False and rejected.source == "disabled"


def test_spend_cap_falls_back_without_calling_llm_result(_enable_llm) -> None:
    llm = _FakeLLM(raises=SpendCapExceededException("cap hit"))
    svc = ValidationService(llm=llm)
    v = svc.validate(_signal(confidence=0.7))
    assert v.source == "spend_cap" and v.approved is True
    assert len(llm.calls) == 1


def test_empty_result_uses_fallback(_enable_llm) -> None:
    svc = ValidationService(llm=_FakeLLM(result=None))
    v = svc.validate(_signal(confidence=0.4))
    assert v.source == "fallback" and v.approved is False


def test_llm_approved_result_parsed_into_validation(_enable_llm) -> None:
    llm_result = {
        "approve": True,
        "confidence": 0.82,
        "reasoning": "clean reversal",
        "adjusted_stop": 97.5,
    }
    svc = ValidationService(llm=_FakeLLM(result=llm_result))
    v = svc.validate(_signal())
    assert isinstance(v, Validation)
    assert v.approved is True and v.confidence == pytest.approx(0.82)
    assert v.adjusted_stop == 97.5 and v.source == "llm"
