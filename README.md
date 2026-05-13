# trading-poc

Automated trading bot focused on safe paper-trading operations first, then live-readiness.

This project runs a scheduler during NSE hours, executes strategy pipelines, applies risk gates, persists all actions to SQLite, and exposes control/report APIs plus a realtime UI.

## What this project does

- Runs every `RUN_INTERVAL_SEC` during market hours.
- Fetches candles for watchlist symbols.
- Generates signals via strategies.
- Optionally validates via LLM.
- Applies risk-engine gates.
- Executes through paper broker (or live broker when explicitly enabled).
- Auto square-offs at `SQUARE_OFF_TIME`.
- Emits end-of-day summary and exports reports.

## Current status (May 2026)

Done:
- Paper-first runtime flow is stable (scheduler, risk, execution, EOD summary).
- NSE holiday-aware market-day checks are implemented.
- Control center UI is available at `/ui`.
- WebSocket live feed and optimize SSE streaming are implemented.
- EOD export endpoints (`json` and `csv`) are implemented.
- Paper readiness endpoint is available at `/ops/paper-ready`.

Next:
- Live-mode order lifecycle reconciliation.
- Optional API authentication for public AWS deployments.
- Walk-forward validation and parameter quality gates.

## Quick start (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Recommended paper settings in `.env`:

```text
MODE=paper
BROKER=paper
PAPER_TRADE=true
OPENROUTER_ENABLED=false
AUTO_RUN_ENABLED=true
```

Run server:

```powershell
uvicorn app.main:app --reload
```

Open:
- API docs: `http://127.0.0.1:8000/docs`
- UI: `http://127.0.0.1:8000/ui`

## AWS systemd setup

Service file: `deploy/systemd/trading-poc.service`

```bash
sudo cp deploy/systemd/trading-poc.service /etc/systemd/system/trading-poc.service
sudo systemctl daemon-reload
sudo systemctl enable trading-poc
sudo systemctl start trading-poc
sudo systemctl status trading-poc
journalctl -u trading-poc -f
```

## Operational endpoints

- `GET /health`
- `GET /ops/paper-ready`
- `GET /runner/status`
- `POST /runner/start`
- `POST /runner/stop`
- `GET /report/today`
- `GET /report/today/export?format=json|csv`
- `GET /report/day/{YYYY-MM-DD}/export?format=json|csv`
- `GET /watchlist`
- `POST /watchlist`
- `DELETE /watchlist/{symbol}`
- `POST /watchlist/persist`
- `POST /optimize/run`
- `GET /optimize/jobs`
- `POST /optimize/cancel/{job_id}`
- `WS /ws/live`

## Backtest and optimize

```powershell
python -m app.backtest.runner --symbol NIFTY --strategy rsi_reversal --from 2025-01-01 --to 2025-04-01 --interval 5m
python optimize_all.py --symbol NIFTY --from 2024-01-01 --to 2025-01-01 --trials 50
```

## Test

```powershell
pytest -q
```

## Full workflow guide

For complete understanding (what, why, how, where, and all useful commands), read:
- `docs/WORKFLOW.md`
- `docs/ARCHITECTURE.md`
- `docs/plan.md`

