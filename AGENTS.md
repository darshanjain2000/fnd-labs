# trading-poc — Agent & Contributor Guidelines

> Read `docs/ARCHITECTURE.md` for a full component map, `docs/plan.md` for roadmap status, and `docs/WORKFLOW.md` for full operator workflow and commands.
> This file exists to orient AI agents and new contributors so they can work faster and safer.

---

## 1. What This Project Is

An automated Equity trading bot that runs a 60-second loop during NSE market hours (IST Mon-Fri 09:15-15:30).
Each tick: fetch OHLCV candles → run strategies → LLM validation → risk gate → broker execution → persist.
All state lives in SQLite; all control is via a FastAPI HTTP API.

**Mode switch**: `PAPER_TRADE=true` (default) = zero real money. `BROKER=angel` + `PAPER_TRADE=false` = live orders.

---

## 2. Architecture at a Glance

```
Scheduler (heartbeat every 60s)
  └─ per-symbol pipeline:
             SignalAgent (enabled strategy set)
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
Target: **all tests pass**.

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

### After Coding (Mandatory)

Update required .md file be it AGENTS.md, doc/ARCHITECTURE.md or doc/plan.md with relevent changes along with .env.local as well.

---

## 5. Code Style

# Coding Style Guide

General coding patterns and conventions to follow when writing code in this developer's style. Technology-agnostic unless noted.

## Architecture

Strict layered architecture. Never skip layers or mix concerns across them.

```
Models → Data Access → Services → Controllers → API Layer
```

| Layer | Responsibility |
|---|---|
| **Models** | Data shapes, validation, enums |
| **Data Access** | DB/external queries only, no logic |
| **Services** | All business logic, no HTTP/transport concerns |
| **Controllers** | Thin delegation — calls services, returns results |
| **API Layer** | HTTP binding, auth, error-to-response mapping |

---

## File & Directory Structure

- One file per logical unit — `{entity}_{layer}.py`
- Group by layer, not by feature

```
src/
  models/
  dal/
  services/
  controllers/
  routers/
  tasks/
  utils/
  enums/
```

---

## Naming Conventions

| Thing | Style | Example |
|---|---|---|
| Classes | PascalCase | `UserService`, `OrderRepository` |
| Functions / methods | snake_case, verb-first | `get_user`, `build_filter_query`, `process_batch_recursively` |
| Variables | snake_case, descriptive | `subscription_guid`, `batch_results` |
| Booleans | `is_` / `has_` prefix | `is_deleted`, `has_access` |
| Collections | plural | `user_ids`, `batch_results` |
| Files | snake_case | `order_service.py`, `response_filter_helper.py` |
| Constants / status enums | IntEnum PascalCase members | `ProcessingStatus.IN_PROGRESS` |

No abbreviations unless universally understood. `guid` is fine. `sub` for subscription is not.

---

## Imports

Order: **stdlib → third-party → local**. Blank line only before local imports.

```python
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from enum import IntEnum

from pydantic import BaseModel, Field
from fastapi import APIRouter

from app_settings import AppSettings
from models.user import User
from utils.logger import logger
```

- Prefer `from module import Name` over `import module` then `module.Name`
- No aliasing on local imports
- Lazy imports inside methods only for circular imports or optional heavy dependencies

---

## Data Models

All data structures use **Pydantic `BaseModel`**. No plain dicts or dataclasses for domain objects.

```python
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any

class CreateOrderRequest(BaseModel):
    user_id: str
    items: List[str]
    metadata: Optional[Dict[str, Any]] = None
    priority: int = Field(default=1, ge=1, le=5)
```

- `Field()` for defaults, constraints, and documentation
- `@field_validator()` for custom validation logic
- `.model_dump()` for serialization
- `.get()` with defaults when accessing raw dicts from external sources

**Enums use `IntEnum`:**

```python
from enum import IntEnum

class ProcessingStatus(IntEnum):
    NEW = 0
    IN_PROGRESS = 1
    COMPLETED = 2
    FAILED = 3
```

---

## API Response Pattern

Every endpoint returns a **typed generic response wrapper**. Never return raw dicts or bare models.

```python
class ApiResponse(BaseModel, Generic[T]):
    statusCode: int
    message: Optional[str] = None
    result: Optional[T] = None
    error: Optional[str] = None
```

Usage:

```python
# Success
return ApiResponse[User](statusCode=HTTPStatus.OK, message="Fetched", result=user)

# Error
return ApiResponse[User](statusCode=CustomExceptionCodes.DataNotFound, error=str(e))
```

---

## API Endpoints

```python
from fastapi import APIRouter, Query, Body, Depends
from http import HTTPStatus

router = APIRouter(prefix="/orders", tags=["Orders"])

@router.get("/", response_model=ApiResponse[List[Order]], dependencies=[Depends(auth)])
async def get_orders(
    user_id: str = Query(..., description="The user ID"),
) -> ApiResponse[List[Order]]:
    try:
        result = controller.get_orders(user_id)
        return ApiResponse[List[Order]](statusCode=HTTPStatus.OK, result=result)
    except DataNotFoundException as e:
        return ApiResponse[List[Order]](statusCode=CustomExceptionCodes.DataNotFound, error=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return ApiResponse[List[Order]](statusCode=HTTPStatus.INTERNAL_SERVER_ERROR, error=str(e))
```

- Route handlers are **`async def`**; services and controllers are **sync**
- Always use `Query(...)` / `Body(...)` with descriptions for explicit parameter documentation
- HTTP status codes from `http.HTTPStatus`
- Catch specific exceptions first, generic `Exception` last
- Auth applied via `dependencies=[Depends(auth)]`

---

## Controllers

Thin. Zero business logic. Calls services and returns results.

```python
class OrderController:
    def __init__(self):
        self.service = OrderService()

    def get_orders(self, user_id: str) -> List[Order]:
        return self.service.get_orders_for_user(user_id)
```

Always sync — no `async def`.

---

## Services

All business logic lives here. Always sync. No HTTP or transport concerns.

```python
class OrderService:
    def __init__(self):
        self.order_dal = OrderDAL()

    def get_orders_for_user(self, user_id: str) -> List[Order]:
        logger.set_context(user_id=user_id)
        logger.info("Fetching orders")
        orders = self.order_dal.find_by_user(user_id)
        if not orders:
            raise DataNotFoundException(f"No orders found for user {user_id}")
        return orders
```

- Set logger context with relevant IDs at the start of every public method
- Raise custom exceptions on failure — **never return `None`** to signal failure
- Do not catch exceptions unless you can meaningfully recover; let them propagate

---

## Data Access Layer

Queries only. No business logic. Always deserialize raw results into Pydantic models before returning.

```python
class OrderDAL(BaseRepository):
    def __init__(self):
        super().__init__()
        self.collection = get_db_connection()["orders"]

    def find_by_user(self, user_id: str) -> Optional[List[Order]]:
        docs = self.filter({"userId": user_id})
        if not docs:
            return None
        return [Order(**doc) for doc in docs]
```

- Use `.get(key, default)` for raw dict access
- Never let raw DB documents leak out of this layer

---

## Error Handling

Define custom exceptions with integer error codes via `IntEnum`:

```python
from enum import IntEnum

class CustomExceptionCodes(IntEnum):
    DataNotFound = 601
    InvalidRequest = 602
    ProcessingFailed = 603

class DataNotFoundException(Exception):
    def __init__(self, message="Data not found", error_code=CustomExceptionCodes.DataNotFound.value):
        super().__init__(message)
        self.error_code = error_code
```

Rules:
- **Services**: raise, don't catch (unless recovery is possible)
- **Routers**: catch specific → catch generic, map all to `ApiResponse`
- **Background tasks**: catch everything, return status dict — never raise
- Never `except: pass` or bare `except`
- Always log before re-raising or returning error responses

---

## Logging

Use the project's context-aware logger. Never use `print()` or raw `logging` directly.

```python
from utils.logger import logger

# Set request-scoped context once at method entry
logger.set_context(user_id=user_id, order_id=order_id)

logger.info("Processing order")
logger.warning("Retrying after transient failure")
logger.error(f"Failed to reach payment service: {str(e)}")
logger.exception(f"Unexpected error: {str(e)}")  # includes stack trace
```

- Context format: `[key=value][key2=value2] message`
- Always include `str(e)` in error/exception messages
- Use f-strings for all log messages

---

## Configuration

Use a **singleton settings class** loaded from environment-specific config files. Never hardcode values.

```python
# Pattern
class AppSettings:
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not AppSettings._initialized:
            self._load()
            AppSettings._initialized = True
```

- Config files per environment: `dev.json`, `uat.json`, `prod.json`
- Group settings by domain: `settings.database`, `settings.cache`, `settings.external_api`
- Use `@property` for lazy initialization of clients/connections
- **Never hardcode**: URLs, API keys, DB names, timeouts, magic strings

---

## Batch Processing

For large datasets: paginate, process in batches, consolidate results.

```python
batch_size = 500
total_pages = (total_count + batch_size - 1) // batch_size  # ceiling division

results = []
for page in range(1, total_pages + 1):
    batch = dal.get_page(query, page=page, page_size=batch_size)
    results.append(process_batch(batch))

final = consolidate(results)
```

---

## Parsing Structured Data from Unstructured Text

When extracting structured data (JSON) from free-form text (e.g., LLM output), always use regex extraction before parsing, and handle failures with fallbacks:

```python
import re, json

match = re.search(r'\{.*\}', raw_text, re.DOTALL)
if match:
    data = json.loads(match.group())
else:
    data = default_value
```

---

## Type Annotations

Every public method has full annotations including return type:

```python
def get_orders(
    self,
    user_id: str,
    status: Optional[ProcessingStatus] = None,
) -> List[Order]:
```

Use `typing` module: `Dict[str, Any]`, `List[str]`, `Optional[str]`, `Tuple[A, B]`.

---

## Code Style

- 4-space indentation
- F-strings for all string interpolation — no `%` formatting or `.format()`
- `is None` / `is not None` — never `== None`
- `if value:` for truthiness checks
- `.get(key, default)` for dict access
- Blank lines between class methods
- Inline comments only when the *why* is non-obvious — never explain *what*

---

## What to Avoid

- `except: pass` or catching `Exception` without logging
- Hardcoded config values anywhere in code
- Plain dicts for domain objects — use Pydantic models
- `print()` for any output — use the logger
- `async def` in service or data access layers — async only at the API boundary
- Magic numbers or magic strings — use enums and named constants
- Returning `None` from services to signal failure — raise a typed exception
- Global mutable state
- String concatenation for building queries, prompts, or structured content
- Broad try/except blocks — keep try blocks as narrow as possible



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
- `pytest -q` must stay green after every change. Baseline: 104 tests (102 passing + 2 skipped, network-gated).

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

#### Single-Symbol Backtest
Run a backtest for one strategy and symbol:
```powershell
python -m app.backtest.runner --symbol NIFTY --strategy rsi_reversal --from 2025-01-01 --to 2025-04-01 --interval 5m
```

#### Batch Backtest — Modes Overview
`batch_backtest.py` supports multiple modes. Pick the mode based on what you want to validate.

Mode quick guide:
- `baseline` (default): per-strategy isolated backtest using default params.
- `--use-optimized`: per-strategy isolated backtest using `config/params_{symbol}.yaml`.
- `--live-parity`: closer to runtime signal behavior (enabled strategies + ensemble selection from `.env`).
- `--orchestrator-parity`: highest-fidelity entry path (signal -> validation -> risk -> execution in simulation mode).

All modes append to:
- `backtest/reports/results.csv`
- `backtest/reports/trades.csv`

#### Batch Backtest — Baseline and Optimized
```powershell
# Baseline run (default params):
python batch_backtest.py --watchlist nse20 --from 2025-04-01 --to 2026-04-23 --interval 5m

# With optimized params (reads config/params_{symbol}.yaml per symbol):
python batch_backtest.py --watchlist nse20 --from 2025-04-01 --to 2026-04-23 --interval 5m --use-optimized

# Custom capital / risk:
python batch_backtest.py --watchlist nse20 --from 2025-01-01 --to 2026-01-01 --interval 5m --capital 50000 --risk-pct 1.5
```
Flags:
- Symbol/date/data: `--watchlist nse20`, `--symbols ADANIENT VEDL`, `--from`, `--to`, `--interval`, `--exchange`
- Risk/execution sim: `--capital`, `--lot-size`, `--risk-pct`, `--trailing-atr`
- Param source: `--use-optimized`
- Conviction mode: `--ensemble N`, `--min-confidence`
- Runtime-parity modes: `--live-parity`, `--orchestrator-parity`

#### Ensemble Backtest — Conviction Filter Simulation
When `--ensemble N` is passed, `batch_backtest.py` also runs `run_ensemble_backtest()` which evaluates **all** strategies per bar and only enters a trade when N or more agree on the same side. This simulates the live pipeline's `min_strategy_agreement` logic.

```powershell
# Require 2 strategies to agree before entering (closest to live pipeline):
python batch_backtest.py --symbols JSWSTEEL --from 2025-04-23 --to 2026-04-23 --interval 5m --use-optimized --ensemble 2

# Full watchlist, ensemble 2, min confidence 0.6:
python batch_backtest.py --watchlist nse20 --from 2025-04-23 --to 2026-04-23 --interval 5m --use-optimized --ensemble 2 --min-confidence 0.6
```

Results appear as strategy `"ensemble_2"` (or `"ensemble_N"`) in `results.csv`.

**Key difference from single-strategy backtest**: Individual backtests test each strategy in isolation (no ensemble, no LLM, no risk gates). The ensemble backtest matches how the live pipeline filters trades — use it to get realistic trade counts and win rates.

#### Live-Parity Backtest (from .env settings)
Use this when you want `.env`-driven strategy/gate behavior with optimized params and ensemble selection logic.

```powershell
# Uses enabled strategies and gates from .env, plus optimized params.
python batch_backtest.py --live-parity --symbols ZENTEC GRAVITA VEDL ADANIPORTS RECLTD --from 2026-03-24 --to 2026-04-24 --interval 5m

# Override agreement threshold for this run only (instead of .env value)
python batch_backtest.py --live-parity --ensemble 2 --symbols ZENTEC GRAVITA --from 2026-03-24 --to 2026-04-24 --interval 5m

# Override confidence threshold for this run only
python batch_backtest.py --live-parity --min-confidence 0.65 --symbols ZENTEC GRAVITA --from 2026-03-24 --to 2026-04-24 --interval 5m
```

Notes:
- If `--ensemble` is omitted in live-parity mode, `.env` `MIN_STRATEGY_AGREEMENT` is used.
- If `--min-confidence` is omitted in live-parity mode, `.env` `MIN_SIGNAL_CONFIDENCE` is used.

#### Orchestrator-Parity Backtest (highest fidelity)
Use this when you want backtest entry decisions to follow runtime pipeline order as closely as possible.

Pipeline used per bar:
- `SignalService` -> conviction selection -> `ValidationService` -> `RiskEngine` -> simulated `ExecutionService`

```powershell
# Full orchestrator-parity on selected symbols
python batch_backtest.py --orchestrator-parity --symbols ZENTEC GRAVITA VEDL ADANIPORTS RECLTD --from 2026-03-24 --to 2026-04-24 --interval 5m

# Same mode on the full watchlist
python batch_backtest.py --orchestrator-parity --watchlist nse20 --from 2026-03-24 --to 2026-04-24 --interval 5m
```

Notes:
- This mode is slower than baseline/optimized runs.
- It is best used for final validation before paper/live deployment.

#### env_backtest.py (date-only runner, config from .env)
`env_backtest.py` is the easiest runner when you want to pass only dates.
It auto-reads from `.env`:
- symbols from `WATCHLIST`
- strategies from `ENABLED_STRATEGIES`
- gates and thresholds from settings

```powershell
# Default mode = orchestrator parity
python env_backtest.py --from 2026-03-24 --to 2026-04-24

# Explicit orchestrator mode
python env_backtest.py --from 2026-03-24 --to 2026-04-24 --mode orchestrator

# Live-parity mode (faster than orchestrator mode)
python env_backtest.py --from 2026-03-24 --to 2026-04-24 --mode live-parity

# Optional overrides
python env_backtest.py --from 2026-03-24 --to 2026-04-24 --interval 5m --capital 25000 --lot-size 1 --risk-pct 1.0 --trailing-atr 0.0
```

Tip for API quota windows:
- If Angel returns `AB1021 (Too many requests)`, retry with fewer symbols or narrower date range.

#### Optuna Hyperparameter Optimization — Single Symbol
Runs all 7 strategies for one symbol. Writes `config/params_{symbol}.yaml`. Trials persist in `config/optuna_studies.db` — re-runs add to existing trials (warm-start), they do not restart.
```powershell
# All 7 strategies, last 5 years (default), 100 trials:
python optimize_all.py --symbol NIFTY

# Override date range and trial count:
python optimize_all.py --symbol NIFTY --from 2024-01-01 --to 2026-01-01 --trials 200

# Optimize for win rate instead of Sortino ratio:
python optimize_all.py --symbol NIFTY --from 2024-01-01 --to 2026-01-01 --trials 100 --metric win_rate
```

#### Batch Optimize — All Symbols
`batch_optimize.py` (root) runs `optimize_all.py` for every symbol in a watchlist. Default: last 2 years, 100 trials per strategy.
```powershell
# Full NSE20 watchlist, 100 trials per strategy (default):
python batch_optimize.py --watchlist nse20 --from 2024-04-23 --to 2026-04-23 --interval 5m

# Quick 50-trial test on specific symbols:
python batch_optimize.py --symbols JSWSTEEL BAJAJFINSV --trials 50 --from 2024-04-23 --to 2026-04-23
```
Flags: `--watchlist nse20`, `--symbols`, `--from`, `--to`, `--interval`, `--trials` (default 100)

> **Note**: `TATAMOTORS` and `ZOMATO` are always skipped — Angel API token not found in local scrip master. `GRAVITA` may fail intermittently.

#### Compare Backtest Runs (Baseline vs Optimized)
`compare_backtest.py` (root) reads `backtest/reports/results.csv`, picks the last two `run_at` timestamps, and prints a side-by-side delta table (per-strategy and per-symbol P&L, trade count, profitable runs).
```powershell
# Auto-compare last two runs (baseline vs optimized):
python compare_backtest.py

# Pin specific runs by timestamp:
python compare_backtest.py --baseline "2026-04-22 22:45:52" --optimized "2026-04-22 23:23:11"
```

#### YAML Convention & Optuna Persistence
- Optimized params: `config/params_{symbol_lower}.yaml` (e.g. `params_jswsteel.yaml`).
- Optuna study history: `config/optuna_studies.db` (SQLite). Each study is named `{strategy}__{symbol}`. Re-running adds trials without resetting — **warm-start is automatic**.
- The live pipeline (`SignalAgent`) auto-loads `config/params_{symbol}.yaml` on startup for every enabled symbol.
- To inspect stored trials: `optuna-dashboard sqlite:///config/optuna_studies.db` (requires `optuna-dashboard` package).

#### Workflow: Baseline → Optimize → Validate → Compare
```powershell
# 1. Baseline backtest (records pre-optimization P&L)
python batch_backtest.py --watchlist nse20 --from 2025-04-01 --to 2026-04-23 --interval 5m

# 2. Optimize (100 trials, 2yr data — results persist in optuna_studies.db)
python batch_optimize.py --watchlist nse20 --from 2024-04-23 --to 2026-04-23 --trials 100

# 3. Re-run backtest with optimized params
python batch_backtest.py --watchlist nse20 --from 2025-04-01 --to 2026-04-23 --interval 5m --use-optimized

# 4. Compare
python compare_backtest.py
```

#### Research: Path to 80% Win Rate
Current per-trade win rate ~45-50% from ~14k trades across 18 symbols. Stacked gates (implement in order) to reach 80%:
1. Raise `min_strategy_agreement` to 3 in `.env` (cuts trade count >50%, keeps only highest-conviction)
2. Volume confirmation: require volume > 1.5× 20-bar avg at entry
3. ATR filter: skip signals when ATR < 0.5% of price
4. Optimize with `--metric win_rate` instead of Sortino
5. Hard regime gate: only momentum strats in trending regime, only mean-reversion in ranging
6. R:R gate in RiskEngine: `target / SL ≥ 2.0`
7. Walk-Forward Efficiency gate: only deploy params with `OOS_sortino / IS_sortino ≥ 0.7`

See `docs/plan.md` sections 3H–3K for full detail.

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
