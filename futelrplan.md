# trading-poc Full Future Architecture Plan

Last updated: May 13, 2026

Objective: define a production-grade, high-speed architecture for database, FastAPI, frontend, and AI-driven trade decisions, as a single consolidated todo list (non-phase).

## Master implementation list

1. Move primary runtime storage from SQLite to PostgreSQL (AWS RDS) with managed backups and point-in-time recovery.
2. Add Alembic migrations and make migration checks mandatory in CI before merge/deploy.
3. Redesign schema for event-level trading data capture, not only summary rows.
4. Keep core entities (`signals`, `trades`, `audit_log`) and add normalized live-trading entities.
5. Add `order_events` table for full broker lifecycle (`PLACED`, `ACK`, `PARTIAL`, `FILLED`, `REJECTED`, `CANCELLED`).
6. Add `fill_events` table for per-fill quantity/price/timestamp details.
7. Add `risk_decisions` table with gate-by-gate pass/fail, thresholds, and rejection reason.
8. Add `strategy_features` table storing model/indicator features at signal time.
9. Add `market_snapshots` table for candle/tick snapshot at signal and execution timestamps.
10. Add `execution_metrics` table for latency, slippage, retry count, and broker roundtrip stats.
11. Add `ai_decisions` table for prompt version, model, confidence, reasoning summary, cost, latency, and outcome.
12. Add `ai_cost_ledger` table for per-day and per-symbol spend accounting.
13. Add `system_health_events` table for scheduler health, service restarts, API errors, and dependency outages.
14. Add `config_history` table to persist every runtime config change with who/when/what.
15. Add strict foreign keys and constraints across all critical tables.
16. Add required indexes for hot paths (`symbol`, `status`, `opened_at`, `event_time`, `order_id`, `trade_id`).
17. Add table partitioning for high-volume event tables by day or month.
18. Add retention policies and archival jobs for cold event data.
19. Add read-optimized views/materialized views for dashboard and reporting workloads.
20. Add idempotency keys on write-heavy endpoints and broker callback handlers.
21. Add transactional outbox for reliable async event delivery to websocket/notifications.
22. Add retry-safe write patterns for broker updates and reconciliation jobs.
23. Add startup reconciliation process between DB open state and broker live state.
24. Add periodic reconciliation job to detect and heal position/order mismatches.
25. Add explicit DB connection pooling settings for low latency and high concurrency.
26. Add API-level request tracing (`request_id`, `trade_id`, `order_id`) across logs and DB writes.
27. Add query budget monitoring for slow SQL detection and optimization.
28. Add endpoint-level performance budgets (p50/p95/p99 latency targets).
29. Add API response caching for heavy read endpoints that do not require real-time freshness.
30. Add pagination + cursor-based APIs for large list endpoints.
31. Add asynchronous background workers for heavy tasks (optimization, analytics aggregation, archival).
32. Add websocket stream throttling and batching policy for high-frequency updates.
33. Add contract-first API design with strict request/response models and versioning.
34. Add auth and RBAC for all non-public operational endpoints.
35. Add secret management via AWS Secrets Manager (remove sensitive reliance on local env files in production).
36. Add rate limiting and abuse protection on public API surfaces.
37. Add circuit breakers and timeout strategy on all external integrations (broker, AI provider).
38. Add fallback behavior matrix for each integration failure mode.
39. Add standardized domain events for all lifecycle transitions (signal created, risk rejected, trade opened, trade closed).
40. Add event replay tooling for incident debugging and backfill.
41. Add robust scheduler state model with persisted tick metadata and restart continuity.
42. Add deterministic audit trail guarantees for every trade-affecting decision.
43. Add frontend state architecture for live trading data (normalized store + websocket reducers + stale data controls).
44. Add frontend telemetry surfaces for latency, slippage, AI confidence, and risk rejection reasons.
45. Add advanced dashboard modules: order lifecycle timeline, execution quality, symbol health, and strategy diagnostics.
46. Add drill-down pages from aggregate metrics to raw event records.
47. Add configurable watchlists, strategy packs, and runtime profiles in frontend with safe guardrails.
48. Add frontend role-based UI visibility matching backend RBAC.
49. Add frontend performance optimization (virtualized tables, incremental rendering, websocket diff updates).
50. Add full-text and structured filtering across signals, trades, and audit events.
51. Add report builder APIs and export jobs for CSV/JSON/parquet artifacts.
52. Add AI prompt registry with versioned templates and rollback support.
53. Add AI decision policy engine (when to call AI, when to skip, max latency budget, max cost budget).
54. Add AI shadow-mode execution tracking (record AI suggestion without executing) for controlled evaluation.
55. Add AI model routing logic (fast model for low-risk cases, stronger model for edge cases).
56. Add post-trade attribution pipeline linking PnL to signal, risk decision, and AI decision lineage.
57. Add walk-forward and out-of-sample quality checks before strategy parameter promotion.
58. Add strategy promotion workflow with approval gates and automatic rollback triggers.
59. Add feature flags for controlled rollout of strategy, AI, and risk changes.
60. Add deployment topology with separate environments (`dev`, `staging`, `prod-paper`, `prod-live`).
61. Add infrastructure as code for reproducible provisioning (network, compute, DB, secrets, monitoring).
62. Add blue/green or rolling deploy strategy with health-gated cutover.
63. Add zero-downtime migration playbook for DB schema evolution.
64. Add disaster recovery documentation and restore drills.
65. Add SLOs/SLIs for scheduler uptime, order latency, data freshness, and API reliability.
66. Add centralized observability stack (metrics, logs, traces, alerting dashboards).
67. Add on-call alerts for critical failures (scheduler down, broker down, DB saturation, AI spend breach, reconciliation mismatch).
68. Add synthetic health checks that validate full trading path in paper mode.
69. Add end-to-end test harness for trade lifecycle in CI against ephemeral PostgreSQL.
70. Add load tests for API read/write and websocket throughput.
71. Add data quality checks for missing candles, stale quotes, and abnormal feature values.
72. Add governance docs for schema contracts, API contracts, and event contracts.
73. Add runbooks for incident classes (order stuck, stale market data, reconciliation breach, AI outage).
74. Add compliance-ready immutable audit export process.
75. Add cost controls for RDS, AI calls, and compute autoscaling with budget alerts.
76. Add final go-live checklist requiring all critical architecture controls to pass before enabling real-money mode.

## Decision recommendation for immediate deployment

- Proceed with AWS deployment now in paper mode using current stack.
- Treat this file as the authoritative build list for the production-grade architecture before live-trading activation.
