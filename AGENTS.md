# trading-poc — Agent & Contributor Guidelines

> Read `docs/ARCHITECTURE.md` for a full component map and `docs/plan.md` for the roadmap.
> This file exists to orient AI agents and new contributors so they can work faster and safer.

---

## 1. What This Project Is

An automated F&O trading bot that runs a 60-second loop during NSE market hours (IST Mon-Fri 09:15-15:30).
Each tick: fetch OHLCV candles → run strategies → LLM validation → risk gate → broker execution → persist.
All state lives in SQLite; all control is via a FastAPI HTTP API.

**Mode switch**: `PAPER_TRADE=true` (default) = zero real money. `BROKER=angel` + `PAPER_TRADE=false` = live orders.

---

## 2. Architecture at a Glance

```
Scheduler (heartbeat every 60s)
  └─ per-symbol pipeline:
       SignalAgent (3 strategies)
         → ValidationAgent (LLM via OpenRouter, optional)
           → RiskEngine (7 hard gates)
             → ExecutionAgent (broker + SQLite)
```

Hot-path files (read these before touching the pipeline):
- [app/engine/orchestrator.py](app/engine/orchestrator.py) — glues all agents together, returns `PipelineOutcome`
- [app/engine/risk_engine.py](app/engine/risk_engine.py) — **never bypass this**; AI cannot override it
- [app/services/scheduler.py](app/services/scheduler.py) — the event loop; parallel candle fetch via `asyncio.gather`
- [app/config.py](app/config.py) — every toggle lives here; all read from `.env`

---

## 3. Build & Test

```powershell
# Install
pip install -r requirements.txt

# Run all tests (must stay green)
python -m pytest -q

# Start server (paper mode by default)
uvicorn app.main:app --reload

# Or run directly
python app/main.py
```

When adding a feature, add tests in `tests/`. Run `pytest -q` before finishing.
Target: **all tests pass**. The baseline is 47 tests.

---

## 4. Code Style

### Python Patterns Used Here

- **`from __future__ import annotations`** at the top of every module — enables forward references in type hints without runtime cost.
- **Pydantic v2 models** for API request/response and settings. Use `model_dump()`, not `.dict()`.
- **`@dataclass`** for internal data containers (`Signal`, `PipelineOutcome`, `RiskDecision`, `DailyStats`).
- **`@lru_cache`** for module-level singletons (broker, orchestrator, risk engine in `deps.py`). Do not instantiate these inline in routes.
- **`structlog`** for all logging. Use event-name keys, not f-strings: `log.info("event_name", key=value)`. Map new event names in `app/core/logging.py`'s `_EVENT_FRIENDLY` dict for pretty output.
- **Protocol / ABC** for extension points: `Broker` is a Protocol in `broker/base.py`; `Strategy` is an ABC in `strategies/base.py`. Add new brokers/strategies by implementing these — never patch the orchestrator.
- **Dependency injection via FastAPI `Depends()`** — brokers, sessions, and engines are injected into routes. See `app/api/deps.py`.
- **SQLAlchemy 2.x** (`future=True`). Use `Session.get(Model, pk)` not `session.query(Model).filter_by(id=pk).first()`. Use context managers for transactions.

### Formatting & Linting

- Style: PEP 8, 4-space indent, max line ~100 chars.
- Type hints on all function signatures.
- No bare `except:` — catch specific exception types.
- Secrets (API keys, PINs, TOTP secrets) live only in `.env` — never hardcode or log them. `config_router.py` masks them in `/config` output.

---

## 5. Key Conventions (Things That Differ From Typical Projects)

### Settings are a singleton — mutate via reload, not import
All config is read once at startup via `get_settings()` (lru_cache). To change runtime settings, `POST /config` then `POST /config/reload`, which calls `reload_settings()` and `reset_cached_singletons()` in `deps.py`. Do **not** read `os.environ` directly.

### Broker abstraction is the seam for testing
`PaperBroker` fits the `Broker` Protocol. Tests inject it directly. When adding features that touch broker calls, write tests using `PaperBroker` or a mock that satisfies the Protocol — do not mock the entire `ExecutionAgent`.

### SQLite migration pattern — no Alembic (yet)
Schema changes to the SQLite DB are handled via `_SQLITE_ADDITIONS` in `app/db.py`, not Alembic migrations. If you add a new column, add an `ALTER TABLE` entry there. Keep it idempotent (check column existence first). **Alembic is a Phase 2+ concern.**

### Logging event names are the contract
`structlog` events are strings like `"signal_rejected_by_risk"`. The pretty-printer in `logging.py` maps these to human sentences. When you add a new loggable event, (1) pick a snake_case name, (2) call `log.info("event_name", **kwargs)`, (3) add it to `_EVENT_FRIENDLY`. Use ASCII-compatible symbols only (Windows cp1252 terminal compatibility).

### Strategies return `Signal | None` — never raise
`Strategy.evaluate()` must return a `Signal` if a setup fires, or `None` if not. Errors bubble up to `SignalAgent`, which catches them per-strategy so one bad strategy can't kill the loop. Do not raise from `evaluate()`.

### Risk engine is the final authority
`RiskEngine.check()` is called **after** AI approval. The LLM cannot override it. Do not add special-case bypasses. If a new rule is needed, add it as a numbered gate with a rejection reason string.

### `is_expiry_day` must be passed explicitly
The scheduler sets `is_expiry_day` based on the symbol's expiry. If you add a new pipeline entry point (e.g., a new API endpoint), pass this flag explicitly — do not default to `False` silently.

---

## 6. Project Structure Quick-Reference

| Path | Responsibility |
|------|---------------|
| `app/config.py` | All settings; sourced from `.env` |
| `app/db.py` | SQLAlchemy engine, session factory, schema migrations |
| `app/main.py` | FastAPI app, router registration, lifespan (DB init + scheduler) |
| `app/agents/` | Decision agents: signal generation, LLM validation, order execution |
| `app/api/` | HTTP endpoints; thin — delegate to agents/engine |
| `app/core/` | Shared utilities: logging setup, IST market calendar |
| `app/engine/` | Orchestrator (pipeline glue), risk engine, regime detector |
| `app/memory/` | SQL-backed similar-trade lookup for LLM context |
| `app/models/` | SQLAlchemy ORM models (`Trade`, `Signal`, `AuditLog`) |
| `app/rag/` | ChromaDB vector store (optional, `MEMORY_SOURCE=rag`) |
| `app/services/` | External integrations: Angel One, LLM client, market data, scheduler |
| `app/services/broker/` | Broker implementations (paper, kite, angel) behind the `Broker` Protocol |
| `app/strategies/` | Trading strategies implementing the `Strategy` ABC |
| `tests/` | pytest test suite — must stay green |
| `docs/` | ARCHITECTURE.md (what it does), plan.md (what's next) |

---

## 7. Adding Common Things

### New Trading Strategy
1. Create `app/strategies/my_strategy.py`, subclass `Strategy`, implement `evaluate()`.
2. Register in `app/strategies/__init__.py` by adding to `ALL_STRATEGIES`.
3. Add `"my_strategy"` to `ENABLED_STRATEGIES` in `.env`.
4. Write at least 2 pytest tests in `tests/test_strategies.py`.

### New API Endpoint
1. Add route to the appropriate file in `app/api/` (or create a new router file).
2. Inject dependencies via `Depends()` — don't instantiate services directly in routes.
3. Register the router in `app/main.py`.
4. Add a test in `tests/test_api.py`.

### New Broker
1. Create `app/services/broker/my_broker.py`, implement the `Broker` Protocol (`place_order`, `cancel_order`, `get_quote`, `mode` property).
2. Wire into `_build_broker()` in `app/api/deps.py`.
3. Add `"my_broker"` to the `BrokerName` literal in `config.py`.

### New Config Toggle
1. Add a field to the `Settings` class in `app/config.py` with a sensible default.
2. Add it to `_EDITABLE_FIELDS` in `config_router.py` if it should be changeable at runtime.
3. Add it to the `ConfigPatch` model in `config_router.py`.

---

## 8. What Helps the AI Work Effectively Here

- **Always read `docs/ARCHITECTURE.md` first** for any non-trivial task. It maps every file to plain-English behavior.
- **Check `app/config.py`** before adding any new behavior flag — the pattern is to add a Pydantic field, not an env read.
- **The pipeline order is fixed**: Signal → Validation → Risk → Execution. Adding a new gate belongs in `RiskEngine`, not the orchestrator.
- **Tests are the spec.** If behavior is unclear, read the test for that module before guessing.
- **`deps.py` is where singletons are wired.** If you can't find where a broker or orchestrator instance comes from, start there.
- **Do not add Alembic migrations** unless the task specifically says Phase 2+ — use `_SQLITE_ADDITIONS` instead.
- **Do not use `print()`** — use `log = get_logger(__name__)` and structured event names.
- **Do not call `get_settings()` in module scope** (other than in `db.py`). Call it inside functions so hot-reload works.
