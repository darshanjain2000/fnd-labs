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

## 4. Before Writing Any Code (AI Agents: Read This First)

1. **Read the existing module first.** Do not duplicate logic that already exists. Check `__init__.py` exports before exploring subdirectories.
2. **Identify inputs, outputs, and failure modes** before writing a single line.
3. **Write implementation and tests together.** Tests are never optional or deferred.
4. **Check `app/config.py`** before adding any new behavior flag — use a Pydantic field, not a raw `os.environ` read.
5. **Check `deps.py`** before instantiating any service — it is the singleton wiring point.
6. **Do not refactor and add a feature in the same change.** One thing at a time.
7. **Reference existing code by name** in your response — do not reprint large blocks that already exist.

### Self-Review Before Outputting (Mandatory)

Before posting any code, verify:
- [ ] Every function has type annotations and a docstring.
- [ ] Every new function has at least one test.
- [ ] `ruff check` and `ruff format` would pass (88-char lines, no unused imports, double quotes).
- [ ] No `TODO`, `pass`, `...`, or `raise NotImplementedError` in production paths.
- [ ] No logic duplicated from an existing helper.
- [ ] `pytest -q` still passes (run it).

---

## 5. Code Style

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

### Logging Rules

- Every long-running or multi-stage task must log its progress to the terminal.
- For tasks that may take more than a few seconds (e.g., LLM calls, parallel fetches), emit a log at the start and on completion.
- The scheduler must emit a live-status heartbeat log at a configurable interval (see `log_heartbeat_interval_sec` in `app/config.py`). This log must show tick count, open positions, realized P&L, and uptime.
- Use structured event names (see `app/core/logging.py`'s `_EVENT_FRIENDLY`) for all logs. Add a new template if your event is not already mapped.
- Never use `print()`. Always use `log.info()` or `log.debug()` with event names and key-value pairs.
- For one-shot tasks, log only on completion unless the operation is expected to take a long time.
- All logs must be human-readable in both 'pretty' and 'json' log formats.

---

## 6. Key Conventions (Things That Differ From Typical Projects)

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

## 7. Project Structure Quick-Reference

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

## 8. Coding Standards (Mandatory for Every Change)

These rules apply to every function, class, and test written in this repo.
They are enforced at review time; violations block merge.

### Formatting

- **Formatter**: `ruff format` (88-char line length). Run on every save.
- **Linter**: `ruff check` — zero warnings before commit.
- Double quotes for all strings.
- 4-space indent, no tabs.

```powershell
# Run both
ruff format app/ tests/
ruff check app/ tests/
```

### Type Annotations & Docstrings

- **Every** function and method must have fully annotated parameters and return type.
- **Every public** function and class must have a Google-style docstring:

```python
def evaluate(self, symbol: str, candles: pd.DataFrame) -> Signal | None:
    """Evaluate strategy on the latest candle batch.

    Args:
        symbol: NSE trading symbol (e.g. "NIFTY").
        candles: OHLCV DataFrame with pre-computed indicators.

    Returns:
        A Signal if a setup fires, None otherwise.
    """
```

- Private helpers need at minimum a one-line docstring.

### Function Design

- **One responsibility per function.** If it does two things, split it.
- **Max 30 lines of logic** per function (not counting docstring).
- **Max 2 levels of nesting.** If you need a third, extract a helper.
- **No global mutable state.** The `_MOCK_QUOTES` dict in `deps.py` is the only accepted exception (test seam).
- **Pure by default.** Functions with side effects must signal it in their name: `save_*`, `send_*`, `write_*`, `update_*`.

### Naming

| Thing | Convention | Example |
|---|---|---|
| Functions & variables | `snake_case` | `compute_indicators` |
| Classes | `PascalCase` | `RiskEngine` |
| Constants | `UPPER_SNAKE_CASE` | `MARKET_OPEN` |
| Private members | `_prefix` | `_apply_sqlite_additions` |
| Test functions | `test_<fn>_<behaviour>` | `test_position_size_rounds_down_to_lot` |

No single-letter names (except `i`, `j` in loops). No abbreviations except `url`, `id`, `db`, `qty`, `pct`.

### Imports

- Order: **stdlib → third-party → local**. One blank line between groups.
- Absolute imports only (`from app.config import get_settings`, never `from . import`).
- Never `import *`. Never leave an unused import.

### Error Handling

- Never `except:` or `except Exception` without a comment explaining why broad catch is justified.
- Never silently swallow exceptions — always `log.warning()` or `log.error()` with context.
- Raise domain-specific exceptions for business logic errors. The `SpendCapExceeded` in `llm_client.py` is the pattern to follow.
- Best-effort cleanup blocks (e.g., cancel SL on broker after close) are the only acceptable `except Exception: pass` — always mark with `# pragma: no cover` and a comment.

---

## 9. Testing Standards (Tests Are Never Optional)

### Structure

- **One test file per source module**: `app/payments.py` → `tests/test_payments.py`.
- **Shared fixtures in `tests/conftest.py` only** — never duplicated across files.
- `pytest -q` must stay green after every change. Baseline: 47 tests.

### What to Write

| Scenario | Required? |
|---|---|
| Happy path: expected inputs → expected outputs | Yes |
| Edge cases: empty, zero, None, boundary values | Yes |
| Error paths: invalid inputs raise correct exception | Yes |
| Mock verification: assert mock called with expected args | Yes |
| Implementation internals | No — test through public interface only |

### Naming

```python
def test_position_size_rounds_down_to_lot() -> None: ...
def test_kill_switch_blocks_all_signals() -> None: ...
def test_validate_raises_on_spend_cap_exceeded() -> None: ...
```

### Determinism & Isolation

- No test depends on state from another test.
- No randomness or real-time logic without mocking (`freezegun` for time, mock for `random`).
- **Mock at the boundary only**: I/O, network, database, broker calls. Never mock inside business logic.
- Always assert mocks were called with the exact expected arguments.

### Coverage Target

- 90%+ on all business logic (agents, engine, strategies, memory).
- Do not write tests just to hit a number — write tests that catch real regressions.

---

## 10. Adding Common Things


### Backtesting & Optimization

#### Backtesting
- Run a backtest for a single strategy and symbol:
  ```powershell
  python -m app.backtest.runner --symbol NIFTY --strategy rsi_reversal --from 2025-01-01 --to 2025-04-01 --interval 5m
  ```

#### Optuna Hyperparameter Optimization
- Run Optuna optimization for all 7 strategies on a symbol (default: last 5 years):
  ```powershell
  python optimize_all.py --symbol NIFTY
  ```
- This creates `config/params_nifty.yaml` with best params for each strategy. The live pipeline will auto-load these for that symbol.
- To override date range or trials:
  ```powershell
  python optimize_all.py --symbol NIFTY --from 2024-01-01 --to 2025-01-01 --trials 50
  ```

#### YAML Convention
- Optimized params are always saved as `config/params_{symbol}.yaml` (lowercase symbol).
- Each file contains a mapping of strategy name to its best parameters.
- The live pipeline (SignalAgent) will use these automatically if present.

---

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

## 11. Known Gaps in the Current Codebase

These are real issues already identified by audit. Fix them opportunistically when touching nearby code — do not batch-fix all at once.

| File | Issue | Priority |
|---|---|---|
| `app/agents/execution_agent.py` | Most methods lack Google-style docstrings | Medium |
| `app/agents/validation_agent.py` | `validate()` lacks `Args/Returns` docstring | Medium |
| `app/agents/signal_agent.py` | `generate()` lacks docstring | Low |
| `app/services/llm_client.py` | `except Exception` in `chat_json` is intentionally broad but undocumented — add a comment | Low |
| `app/services/angel_session.py` | Multiple `except Exception` blocks — each needs a comment explaining why | Medium |
| `tests/` | No `conftest.py` — shared fixtures like `_sig()` and `_engine()` are duplicated across test files | Medium |
| `tests/test_risk_engine.py` | Test helper `_sig()` not typed or docstringed | Low |
| All `app/api/` routes | Route handlers lack docstrings (Swagger shows blank descriptions) | Low |
| `app/engine/risk_engine.py` | `position_size()` docstring is one line — missing `Args/Returns` | Low |

---

## 12. What Helps the AI Work Effectively Here

- **Always read `docs/ARCHITECTURE.md` first** for any non-trivial task. It maps every file to plain-English behavior.
- **Check `app/config.py`** before adding any new behavior flag — the pattern is to add a Pydantic field, not an env read.
- **The pipeline order is fixed**: Signal → Validation → Risk → Execution. Adding a new gate belongs in `RiskEngine`, not the orchestrator.
- **Tests are the spec.** If behavior is unclear, read the test for that module before guessing.
- **`deps.py` is where singletons are wired.** If you can't find where a broker or orchestrator instance comes from, start there.
- **Do not add Alembic migrations** unless the task specifically says Phase 2+ — use `_SQLITE_ADDITIONS` instead.
- **Do not use `print()`** — use `log = get_logger(__name__)` and structured event names.
- **Do not call `get_settings()` in module scope** (other than in `db.py`). Call it inside functions so hot-reload works.
