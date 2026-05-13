# trading-poc Plan and Status

Last updated: May 13, 2026

## Current objective

Stabilize and operate paper-trading reliably on local and AWS before enabling live mode.

## Done (completed)

## Core runtime
- Scheduler loop with tick-based execution.
- Market-hour gating and EOD square-off.
- NSE holiday-aware market-day checks.
- End-of-day summary event emission.

## Trading pipeline
- Signal -> validation -> risk -> execution flow wired.
- Multiple strategies registered and runnable.
- Risk engine hard gates and position sizing active.
- Signal/trade/audit persistence working.

## Operations and UI
- Control center at `/ui`.
- Runner controls (`/runner/start`, `/runner/stop`, `/runner/status`).
- Watchlist CRUD/search/persist endpoints.
- Optimize run/stream/status/history/cancel endpoints.
- Live websocket feed (`/ws/live`).
- EOD report export endpoints (JSON/CSV).
- Paper readiness endpoint (`/ops/paper-ready`).
- Systemd service template (`deploy/systemd/trading-poc.service`).

## Documentation
- README refreshed.
- Architecture refreshed.
- Workflow guide added (`docs/WORKFLOW.md`).

## In progress

- Final polish and consistency checks across docs and runtime settings.

## Next (near-term)

1. Add optional auth guard for public deployments.
2. Add live-mode order reconciliation and startup sync.
3. Add robust retry/circuit-breaker around broker/network operations.
4. Add daily archival artifacts for EOD summaries.

## Future (mid-term)

1. Walk-forward out-of-sample validation gates.
2. Stronger optimization quality checks before param rollout.
3. LLM A/B measurement harness with cost-vs-value reporting.
4. Production observability stack and deployment hardening.

## Future (long-term)

1. Multi-profile runtime configurations (paper/live/backtest profiles).
2. Backtest result persistence beyond CSV.
3. Extended strategy governance and risk analytics.

## Definition of done for paper-to-live transition

All must be true before enabling live mode:
1. Two weeks stable paper operation without critical runtime failures.
2. Reconciliation checks implemented and validated.
3. Alerting and restart runbooks validated on AWS.
4. Risk controls and kill switch behavior verified under failure drills.

Sign-off checklist reference:
- `docs/RELEASE_CHECKLIST.md`
