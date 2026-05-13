# trading-poc Release Checklist (Paper AWS)

Last updated: May 13, 2026

Use this as a go/no-go sign-off list before paper deployment on AWS.

## A. Build and quality gate

- [x] Full test suite passes (`pytest -q`): 191 passed, 2 skipped.
- [x] Startup import smoke test passes (`from app.main import app`).
- [x] Core scheduler/calendar refactor validated with focused tests.
- [x] Lint gate (`ruff check`) clean.
- [x] Format gate (`ruff format --check`) clean.

Validation commands run:
- `ruff check app tests`
- `ruff format --check app tests`

## B. Paper safety gate

- [x] `MODE=paper`
- [x] `BROKER=paper`
- [x] `PAPER_TRADE=true`
- [x] `OPENROUTER_ENABLED=false` (paper-first phase)
- [x] `AUTO_RUN_ENABLED=true`
- [x] Runtime paper readiness endpoint available: `GET /ops/paper-ready`

## C. Scheduler and market controls

- [x] Market day check is holiday-aware (`is_market_day`).
- [x] Market open check uses trading day + time window.
- [x] EOD square-off and summary emission are active.
- [x] EOD report export endpoints (`json` and `csv`) are available.

## D. Operations and observability

- [x] Realtime UI available at `/ui`.
- [x] WebSocket live stream available at `/ws/live`.
- [x] Runner controls available (`/runner/start`, `/runner/stop`, `/runner/status`).
- [x] Optimize orchestration endpoints available.
- [x] Systemd unit template available at `deploy/systemd/trading-poc.service`.
- [x] One-shot EC2 bootstrap script available at `deploy/systemd/bootstrap_paper_ec2.sh`.

## E. AWS deployment runbook

1. Provision EC2 (Ubuntu, ap-south-1 recommended).
2. Clone repo and create `.env` from `.env.example`.
3. Apply paper safety keys from section B.
4. Install and start systemd service.
5. Validate:
   - `/health`
   - `/ops/paper-ready`
   - `/runner/status`
   - `/report/today`
6. Observe logs for scheduler heartbeat and EOD summary.

## F. Future hardening before live mode

- [ ] Add auth guard for public API exposure.
- [ ] Add order lifecycle reconciliation with broker state.
- [ ] Add startup position/order sync checks.
- [ ] Add retry + circuit-breaker wrappers for broker and network calls.
- [ ] Add alerting (Telegram/email) for failures and kill-switch events.
- [ ] Add walk-forward parameter quality gate for strategy rollout.

## G. Sign-off

- [ ] Engineering sign-off
- [ ] Ops sign-off
- [ ] Paper runtime validation sign-off
