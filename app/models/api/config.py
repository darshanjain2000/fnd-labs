"""Pydantic DTOs for the ``/config`` router."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ConfigPatchOut(BaseModel):
    """Response envelope after a successful ``PATCH /config``."""

    applied: dict[str, Any]
    config: dict[str, Any]


class ConfigReloadOut(BaseModel):
    """Response envelope after a successful ``POST /config/reload``."""

    reloaded: bool
    config: dict[str, Any]
