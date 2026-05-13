# trading-poc Complete Workflow Guide

Last updated: May 13, 2026

This file is the single-source guide for understanding:
- what this project does,
- why it exists,
- how it runs,
- where each responsibility lives,
- and which commands to use for day-to-day work.

## 1. What this project is

trading-poc is an automated trading platform focused on paper-trading stability first.

Core behavior:
1. Runs a scheduler every N seconds during market hours.
2. Fetches candles for watchlist symbols.
3. Produces strategy signals.
4. Optionally validates with LLM.
5. Applies non-bypassable risk gates.
6. Executes with broker abstraction (paper/live).
7. Persists signals, trades, and logs.
8. Emits EOD summary and exposes reports.

## 2. Why this project exists

Purpose:
- Build repeatable, auditable intraday trading execution.
- Separate strategy logic from risk and execution safety.
- Support local experimentation and AWS paper operations before live money.
- Provide operational transparency via APIs, logs, and realtime UI.

## 3. End-to-end runtime workflow

On app start:
1. Load settings from `.env`.
2. Initialize database.
3. Start scheduler automatically if `AUTO_RUN_ENABLED=true`.

On each scheduler tick:
1. Check if market is open (`is_market_open`) and market day (`is_market_day`).
2. If closed, log next open and return.
3. Fetch symbol candles in parallel.
4. Mark-to-market and auto-close SL/target hits.
5. If square-off time reached, force-close all and emit EOD summary.
6. Otherwise run orchestrator per symbol not already in open position.
7. Publish websocket events (`tick_summary`, `trade_opened`, `trade_closed`, `eod_summary`).

Orchestrator workflow:
1. `SignalAgent.generate`
2. `ValidationAgent.validate`
3. `RiskEngine.evaluate`
4. `ExecutionAgent.execute`

## 4. Where things are in the repo

- `app/main.py`: app startup, lifespan, router mounting.
- `app/config.py`: centralized settings and toggles.
- `app/services/scheduler.py`: heartbeat loop and EOD controls.
- `app/core/market_calendar.py`: open-day/open-time checks including holidays.
- `app/engine/orchestrator.py`: pipeline glue.
- `app/engine/risk_engine.py`: hard risk gates and position sizing.
- `app/services/broker/`: paper/live broker implementations.
- `app/routers/`: operational API surface.
- `frontend/index.html`: no-build operator control center.
- `tests/`: unit/integration tests.
- `docs/ARCHITECTURE.md`: architectural map.
- `docs/plan.md`: roadmap and status.

## 5. Required operating modes

Paper-first (recommended default):
- `MODE=paper`
- `BROKER=paper`
- `PAPER_TRADE=true`
- `OPENROUTER_ENABLED=false`
- `AUTO_RUN_ENABLED=true`

Live mode should only be attempted after reconciliation and hardening tasks are complete.

## 6. Daily operator commands

## Environment setup (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

## Run API locally

```powershell
uvicorn app.main:app --reload
```

## Health and runner checks

```powershell
# API health
curl http://127.0.0.1:8000/health

# paper readiness
curl http://127.0.0.1:8000/ops/paper-ready

# scheduler status
curl http://127.0.0.1:8000/runner/status
```

## Manual runner control

```powershell
curl -X POST http://127.0.0.1:8000/runner/start
curl -X POST http://127.0.0.1:8000/runner/stop
```

## Reports and export

```powershell
curl "http://127.0.0.1:8000/report/today"
curl "http://127.0.0.1:8000/report/today/export?format=json"
curl "http://127.0.0.1:8000/report/today/export?format=csv"
```

## Backtest and optimize

```powershell
python -m app.backtest.runner --symbol NIFTY --strategy rsi_reversal --from 2025-01-01 --to 2025-04-01 --interval 5m
python optimize_all.py --symbol NIFTY --from 2024-01-01 --to 2025-01-01 --trials 50
```

## Run test suite

```powershell
pytest -q
```

## 7. AWS deploy workflow (paper)

1. Provision EC2 (Ubuntu preferred).
2. Clone repo and install dependencies.
3. Configure `.env` with paper settings.
4. Install systemd service:

```bash
sudo cp deploy/systemd/trading-poc.service /etc/systemd/system/trading-poc.service
sudo systemctl daemon-reload
sudo systemctl enable trading-poc
sudo systemctl start trading-poc
sudo systemctl status trading-poc
journalctl -u trading-poc -f
```

5. Validate endpoints:
- `/health`
- `/ops/paper-ready`
- `/runner/status`
- `/report/today`

### One-shot bootstrap option

You can run the full setup using the script at `deploy/systemd/bootstrap_paper_ec2.sh`.

```bash
chmod +x deploy/systemd/bootstrap_paper_ec2.sh
./deploy/systemd/bootstrap_paper_ec2.sh <YOUR_REPO_URL> /opt/trading-poc
```

### Exact command sequence (Ubuntu EC2)

```bash
# 1) SSH into instance
ssh -i /path/to/key.pem ubuntu@<EC2_PUBLIC_IP>

# 2) System prep
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip

# 3) Clone project
cd /opt
sudo git clone <YOUR_REPO_URL> trading-poc
sudo chown -R ubuntu:ubuntu /opt/trading-poc
cd /opt/trading-poc

# 4) Python env + deps
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 5) Configure environment
cp .env.example .env
sed -i 's/^MODE=.*/MODE=paper/' .env
sed -i 's/^BROKER=.*/BROKER=paper/' .env
sed -i 's/^PAPER_TRADE=.*/PAPER_TRADE=true/' .env
sed -i 's/^OPENROUTER_ENABLED=.*/OPENROUTER_ENABLED=false/' .env
sed -i 's/^AUTO_RUN_ENABLED=.*/AUTO_RUN_ENABLED=true/' .env

# 6) Install systemd unit
sudo cp deploy/systemd/trading-poc.service /etc/systemd/system/trading-poc.service
sudo systemctl daemon-reload
sudo systemctl enable trading-poc
sudo systemctl restart trading-poc
sudo systemctl status trading-poc --no-pager

# 7) Quick health checks
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/ops/paper-ready
curl -sS http://127.0.0.1:8000/runner/status
curl -sS http://127.0.0.1:8000/report/today

# 8) Tail logs
journalctl -u trading-poc -f
```

## 8. Guardrails for contributors

- Never bypass risk engine.
- Never hardcode secrets.
- Keep settings in `app/config.py`.
- Add tests with all behavior changes.
- Update docs (`README.md`, `docs/ARCHITECTURE.md`, `docs/plan.md`) with meaningful changes.

## 9. Quick troubleshooting

- Scheduler not running:
  - Check `AUTO_RUN_ENABLED` and `/runner/status`.
- No symbols processed:
  - Check `WATCHLIST` and `GET /watchlist`.
- No trades opening:
  - Check risk rejection reason in logs and signal confidence thresholds.
- Market appears closed unexpectedly:
  - Check timezone, market window settings, and holiday date list in `app/core/market_calendar.py`.

## 10. What to read next

- `README.md` for setup and endpoints.
- `docs/ARCHITECTURE.md` for component-level design.
- `docs/plan.md` for roadmap and completion status.
