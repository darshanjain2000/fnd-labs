"""WebSocket live-feed endpoint.

Streams all trading events (tick summaries, trade opens/closes, signals,
MTM updates) to every connected browser client in real time.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logging import get_logger
from app.services.ws_broadcaster import get_broadcaster

log = get_logger(__name__)

router = APIRouter(tags=["websocket"])

_PING_INTERVAL_SEC: int = 20


@router.websocket("/ws/live")
async def live_feed(ws: WebSocket) -> None:
    """WebSocket endpoint that pushes all trading events to connected clients.

    Event types emitted:
    - ``tick_summary``   — end of each scheduler tick (symbols, signals, trades)
    - ``trade_opened``   — a new position was entered
    - ``trade_closed``   — a position was closed (SL / target / EOD / manual)
    - ``signal_generated`` — a strategy signal fired (approved or rejected)
    - ``mtm_update``     — latest prices snapshot after mark-to-market
    - ``scheduler_status`` — scheduler start / stop events
    - ``ping``           — keepalive (every 20 s when idle)

    Clients should reconnect on disconnect (the frontend does this automatically).

    Args:
        ws: The FastAPI WebSocket connection object.
    """
    await ws.accept()
    broadcaster = get_broadcaster()
    q = broadcaster.subscribe()
    log.info("ws_client_connected", total_clients=broadcaster.subscriber_count)
    try:
        while True:
            try:
                event = await asyncio.wait_for(
                    q.get(), timeout=float(_PING_INTERVAL_SEC)
                )
                await ws.send_text(json.dumps(event, default=str))
            except asyncio.TimeoutError:
                # Keepalive ping so the browser's WebSocket doesn't idle-close
                await ws.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        log.info(
            "ws_client_disconnected", total_clients=broadcaster.subscriber_count - 1
        )
    except Exception:
        log.exception("ws_client_error")
    finally:
        broadcaster.unsubscribe(q)
