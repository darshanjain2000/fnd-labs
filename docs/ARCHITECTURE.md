# trading-poc Architecture

Last updated: May 13, 2026

## 1. Purpose

trading-poc is an automated trading system designed to run in paper mode first.

Primary goals:
- Run a deterministic scheduler during NSE hours.
- Execute a strict pipeline: signal -> validation -> risk -> execution.
- Keep all decisions and trades auditable in SQLite.
- Expose full runtime control through FastAPI + realtime UI.

## 2. Runtime flow

Scheduler tick (every `RUN_INTERVAL_SEC`):
1. Check market window and trading day (weekend + NSE holiday-aware).
2. Fetch candles for watchlist symbols (parallel + capped concurrency).
3. Mark-to-market open positions and auto-close on SL/target.
4. Run orchestrator for symbols not already in open trades.
5. Emit websocket tick summary and logs.
6. At square-off time, force-close all and emit EOD summary.

## 3. Fixed decision order

The order is always:
1. Signal Agent
2. Validation Agent (optional LLM)
3. Risk Engine (hard gates)
4. Execution Agent

Risk engine is final authority. LLM cannot override risk rejection.

## 4. Key modules

## Core
- `app/main.py`: FastAPI app startup, router registration, lifespan startup/shutdown.
- `app/config.py`: all settings from `.env` via Pydantic.
- `app/db.py`: SQLAlchemy setup and SQLite additive migrations.
- `app/core/logging.py`: structured + pretty event logging.
- `app/core/market_calendar.py`: IST market calendar helpers with NSE holiday-aware checks.

## Pipeline
- `app/engine/orchestrator.py`: pipeline glue and `PipelineOutcome` generation.
- `app/engine/risk_engine.py`: all hard risk gates and position sizing.
- `app/agents/signal_agent.py`: executes enabled strategies.
- `app/agents/validation_agent.py`: LLM/rules validation.
- `app/agents/execution_agent.py`: order placement and trade lifecycle persistence.

## Market and broker services
- `app/services/angel_session.py`: Angel session, token lookup, candle fetch.
- `app/services/market_data.py`: indicator computation.
- `app/services/broker/paper_broker.py`: simulated order execution.
- `app/services/broker/angel_client.py`: live broker implementation.
- `app/services/scheduler.py`: market loop and EOD behavior.
- `app/services/ws_broadcaster.py`: live event fanout.

## API routers
- `app/routers/runner_router.py`: scheduler start/stop/status.
- `app/routers/report_router.py`: EOD reports and export.
- `app/routers/ops_router.py`: paper-readiness checks.
- `app/routers/watchlist_router.py`: watchlist CRUD/search/persist.
- `app/routers/optimize_router.py`: optimize jobs, logs, history, cancel.
- `app/routers/ws_router.py`: websocket endpoint.

## 5. Data model intent

- `Signal`: every generated signal and validation metadata.
- `Trade`: open/closed positions and realized pnl.
- `AuditLog`: event history for traceability.

## 6. Operations behavior

- Scheduler can auto-start at boot (`AUTO_RUN_ENABLED=true`).
- Outside market hours, it idles (keeps process alive).
- Market-day logic is holiday-aware via `is_market_day`.
- EOD square-off triggers summary log + websocket event.

## 7. Deployment pattern

Recommended paper-first deployment:
- Use `MODE=paper`, `BROKER=paper`, `PAPER_TRADE=true`.
- Keep `OPENROUTER_ENABLED=false` initially.
- Run under systemd using `deploy/systemd/trading-poc.service`.
- Check readiness via `GET /ops/paper-ready`.

## 8. Roadmap status pointer

- Current progress and planned phases: `docs/plan.md`
- Full operator and contributor workflow: `docs/WORKFLOW.md`
