"""HTTP routers for the FastAPI application.

Each module exposes a single ``router`` (``APIRouter``) or a small
collection (e.g. ``router`` + ``report_router``) that ``app.main``
registers. Routers delegate all work to controllers in
``app.controllers``; they never contain business logic themselves.

Every endpoint returns an ``ApiResponse[T]`` envelope so clients can rely
on a uniform shape — including in the error path (global handler in
``app.main``).
"""
from __future__ import annotations
