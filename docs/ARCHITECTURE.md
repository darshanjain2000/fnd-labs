# Architecture & Current Implementation

Last updated: April 19, 2026 · After Phase 1.

A human-language guide to **what the bot actually does today**, how the pieces fit together, and where every behavior lives in code. Read this before touching the repo.

---


## 1. What the bot does, in one paragraph

Every 60 seconds during market hours (IST Mon-Fri 09:15-15:30), the bot fetches fresh 5-minute candles from Angel One for each symbol in its watchlist (currently 8: NIFTY, BANKNIFTY, FINNIFTY, RELIANCE, HDFCBANK, TCS, INFY, ICICIBANK). It runs seven technical strategies on each symbol (RSI reversal, EMA breakout, VWAP pullback, Supertrend, MACD divergence, Bollinger Squeeze, ORB breakout) and collects any signals. Each signal is optionally sent to an LLM (OpenRouter / Claude) for a second opinion using past-trade context from SQL. If approved, a risk engine checks 7 gates (kill switch, daily loss, open-position cap, etc.) and sizes the position. If everything passes, the trade goes to a paper broker (simulated fill with slippage) or Angel One (real order). All OPEN trades are marked-to-market every tick — if price hits stop-loss or target, they auto-close. At 15:20 IST the bot force-closes every remaining open trade (EOD square-off). Every signal, trade, and decision is persisted to SQLite and exposed through a FastAPI HTTP interface.
## Backtesting & Optimization

- Run a backtest for a single strategy and symbol:
       ```powershell
       python -m app.backtest.runner --symbol NIFTY --strategy rsi_reversal --from 2025-01-01 --to 2025-04-01 --interval 5m
       ```
- Run Optuna optimization for all 7 strategies on a symbol (default: last 5 years):
       ```powershell
       python optimize_all.py --symbol NIFTY
       ```
- This creates `config/params_nifty.yaml` with best params for each strategy. The live pipeline will auto-load these for that symbol.
- To override date range or trials:
       ```powershell
       python optimize_all.py --symbol NIFTY --from 2024-01-01 --to 2025-01-01 --trials 50
       ```

### YAML Convention
- Optimized params are always saved as `config/params_{symbol}.yaml` (lowercase symbol).
- Each file contains a mapping of strategy name to its best parameters.
- The live pipeline (SignalAgent) will use these automatically if present.

---

## 2. Component map

```
                              ┌─────────────────────────┐
                              │   FastAPI (app/main.py) │
                              │  HTTP routes + lifespan │
                              └────────────┬────────────┘
                                           │
                                ┌──────────┴──────────┐
                                │  MarketScheduler     │  <- the heartbeat
                                │  (every 60s in IST   │
                                │   market hours)       │
                                └──────────┬──────────┘
                                           │
               ┌─────────────┬─────────────┼─────────────┬──────────────┐
               ▼             ▼             ▼             ▼              ▼
        ┌───────────┐  ┌──────────┐  ┌───────────┐ ┌───────────┐  ┌────────────┐
        │   Angel   │  │ Candle   │  │  Mark-to- │ │  EOD      │  │ New signal │
        │  session  │  │ fetch    │  │  market   │ │ square-off│  │ pipeline   │
        │ (login +  │  │ (parallel│  │  open trades│(15:20)   │  │ per symbol │
        │  scrip mstr)│  │ asyncio  │  │  SL/Target   │  │            │
        └───────────┘  │  gather) │  │  auto-close │  │            │
                       └──────────┘  └───────────┘ └───────────┘  └─────┬──────┘
                                                                        │
                                              ┌──── SIGNAL PIPELINE ────┘
                                              ▼
                    ┌───────────────┬────────────┬───────────┬──────────────┐
                    │ SignalAgent   │ Validation │ RiskEngine│ ExecutionAgent│
                    │ (3 strategies)│  (LLM +    │ (7 gates, │  (broker call,│
                    │               │   memory)  │  sizing)  │   DB persist) │
                    └───────────────┴────────────┴───────────┴──────────────┘
                                                                        │
                                                   ┌────────────────────┘
                                                   ▼
                                      ┌─────────┬──────────┐
                                      │ Paper   │ Angel    │ <- broker swap via
                                      │ Broker  │ (live)   │    config (BROKER=...)
                                      └─────────┴──────────┘
                                                   │
                                                   ▼
                                      ┌──────────────────────┐
                                      │  SQLite: trading.db  │
                                      │  Signal / Trade /    │
                                      │  AuditLog            │
                                      └──────────────────────┘
```

---

## 3. Every file, what it does, in plain English

### Core plumbing

| File | What it does |
|---|---|
| `app/main.py` | FastAPI startup. Mounts all routers. Lifespan handler: runs DB migrations, then starts the scheduler if `AUTO_RUN_ENABLED=true`. |
| `app/config.py` | One Pydantic `Settings` class reading `.env` at boot. Every toggle in the project is defined here (capital, risk caps, strategy list, Angel creds, scheduler times, log format). Hot-reload via `POST /config/reload`. |
| `app/db.py` | SQLAlchemy engine + `SessionLocal`. `init_db()` runs `create_all` then an ALTER TABLE migration helper that adds new columns to existing SQLite DBs (`ai_confidence`, `ai_source` on `signals`). |
| `app/core/logging.py` | structlog setup with a custom pretty renderer (`_friendly_renderer`). Maps 28+ event names to human sentences like "Market CLOSED … next open: Mon 09:15 IST (in 15h 40m)". Uses ASCII markers (`>>`, `[+]`, `[X]`) for Windows cp1252 compatibility. Switches to JSON output if `LOG_FORMAT=json`. |
| `app/core/market_calendar.py` | Simple IST helpers: `now_ist()`, `is_market_open()`, `minutes_to_close()`. Hardcoded 09:15-15:30 Mon-Fri (no NSE holiday list yet — see Phase 2 TODO). |

### Strategies — where signals are born

| File | What it does |
|---|---|
| `app/strategies/base.py` | Abstract `Strategy` class with one method: `evaluate(symbol, candles_df) → Signal \| None`. Defines the `Signal` dataclass (symbol, strategy, side BUY/SELL, entry, stop_loss, target, confidence 0-1, context dict). |
| `app/strategies/rsi_reversal.py` | Mean-reversion. If RSI(14) drops below 30 → BUY. Above 70 → SELL. SL = entry ± 1.5×ATR, Target = entry ± 2×ATR. Confidence scales with how extreme the RSI is. |
| `app/strategies/ema_breakout.py` | Trend follow. When 20-EMA crosses above 50-EMA → BUY. Below → SELL. Fixed confidence 0.6. |
| `app/strategies/vwap_pullback.py` | Intraday pullback. Close within ±0.2% of VWAP AND on correct side of 20-EMA → trade in EMA direction. Fixed confidence 0.55. |

### Agents — the decision pipeline

| File | What it does |
|---|---|
| `app/agents/signal_agent.py` | Runs every enabled strategy on a symbol's candles. Returns list of Signals. Catches per-strategy errors so one bad strategy can't kill the pipeline. |
| `app/agents/validation_agent.py` | Optional LLM second opinion. Calls OpenRouter (Claude 3.5 Sonnet by default) with the signal + last K similar past trades. LLM returns JSON: `{approve, confidence, reasoning, adjusted_stop}`. Falls back to "approve if strategy confidence ≥ `AI_FALLBACK_APPROVE_THRESHOLD`" when LLM is disabled or fails. Records `source: llm \| disabled \| fallback \| spend_cap`. |
| `app/agents/execution_agent.py` | Places entry + SL orders, writes Trade + AuditLog rows, and handles the two auto-close paths: **mark_to_market** (every scheduler tick, close trades where price hit SL/target) and **force_close_all** (at 15:20 square-off). |

### Engine — risk & regime

| File | What it does |
|---|---|
| `app/engine/orchestrator.py` | The glue. Takes a symbol + candles, runs SignalAgent → ValidationAgent → RiskEngine → ExecutionAgent, and returns a `PipelineOutcome`. Persists Signal row with AI confidence + source for later analysis. |
| `app/engine/risk_engine.py` | 7 hard gates: kill switch, max trades/day, max open positions, daily loss cap, expiry-day block, qty-rounds-to-lot, risk-per-trade cap. Position sizing: `qty = floor((capital × risk%) / (entry - stop))` rounded to lot size. Resets daily counters at midnight IST. |
| `app/engine/regime_detector.py` | Classifies market into `trend_up / trend_down / range / high_vol` using EMA20-50 spread and ATR%. **Built but not yet wired into signal selection** — Phase 3 work. |

### Data & broker

| File | What it does |
|---|---|
| `app/services/market_data.py` | `compute_indicators(df)` adds RSI(14), EMA20, EMA50, VWAP, ATR(14) to OHLCV frames. Uses pandas-ta if available, manual numpy fallback otherwise. |
| `app/services/angel_session.py` | Singleton wrapper for Angel SmartConnect. Does TOTP login lazily. Downloads the public scrip master JSON (~50MB, 5M instruments) and caches it 24h — this bypasses the dormant-account `searchScrip` block. `fetch_candles_for_symbol()` returns a pandas OHLCV DataFrame. |
| `app/services/broker/base.py` | `Broker` protocol. `place_order(req) → OrderResult`, `cancel_order`, `get_quote`. Any broker impl just satisfies this. |
| `app/services/broker/paper_broker.py` | Simulated fills. Returns `COMPLETE` immediately at quote price ± random slippage (default 5 bps). No partial fills, no rejections, no fees modeled. |
| `app/services/broker/angel_client.py` | Real Angel orders. Maps order types (MARKET / LIMIT / SL-M / SL) and products (MIS / NRML / CNC) to Angel's names. Resolves symbol → token via scrip master. **No order status polling yet** — Phase 2 work. |
| `app/services/broker/kite_client.py` | Zerodha Kite broker impl, minimal. Not currently used (BROKER=angel in .env). |
| `app/services/llm_client.py` | OpenRouter HTTP client. `chat_json(system, user, schema_hint)` enforces JSON-only response. Tracks daily USD spend vs `OPENROUTER_DAILY_USD_CAP`. Raises `SpendCapExceeded` when hit. |
| `app/services/scheduler.py` | The heartbeat. `MarketScheduler` runs as an asyncio task. Every tick: (1) parallel-fetch candles via `asyncio.gather`, (2) mark-to-market open trades, (3) EOD square-off if past 15:20, (4) run pipeline for each symbol not already in a trade. Logs throttled "Market CLOSED, next open Mon 09:15 IST (in X hours)" when outside hours so you always know it's alive. |

### Memory — feeds context to the LLM

| File | What it does |
|---|---|
| `app/memory/trade_memory.py` | SQL-backed similar-trade lookup. `recent_similar(symbol, strategy, side, k=5)` → last K closed trades. `format_context()` → list of short strings the LLM sees. Default path (`MEMORY_SOURCE=db`). |
| `app/rag/store.py` | Chroma + SentenceTransformer embedding store. Alternative to the SQL path when `MEMORY_SOURCE=rag`. Lazy-init so Chroma never loads if unused. |

### Models — database tables

| Model | Purpose |
|---|---|
| `Signal` | Every signal a strategy ever produced. Includes `ai_approved`, `ai_reasoning`, **`ai_confidence`**, **`ai_source`** (new in Phase 1). |
| `Trade` | Every position opened. `OPEN / CLOSED / CANCELLED`. PnL computed on close. Links back to Signal via FK. |
| `Position` | Unused. Placeholder for future broker-position reconciliation (Phase 2). |
| `AuditLog` | Append-only event log. Every interesting event (trade_opened, signal_rejected_by_ai, scheduler_eod_square_off, ...) dumps a JSON payload here. |

### API routes

| Route | Purpose |
|---|---|
| `GET /` · `GET /health` | Uptime check |
| `POST /analyze` · `POST /analyze/live` | Manual pipeline run — supply candles, or fetch live from Angel |
| `POST /trade/manual` | Manually open a trade |
| `GET /trades` · `GET /trades/{id}` · `POST /trades/{id}/close` | Trade CRUD |
| `GET /signals` · `GET /logs` | Read-only history |
| `GET /admin/positions` · `POST /admin/killswitch/{on\|off}` | Risk view + emergency stop |
| `GET /admin/angel/totp` · `GET /admin/broker/status` | Angel health checks |
| `GET /config` · `PATCH /config` · `POST /config/reload` | Live config view / edit |
| `POST /runner/start` · `POST /runner/stop` · `GET /runner/status` | Scheduler control |
| `GET /report/today` · `GET /report/day/{YYYY-MM-DD}` | EOD performance summary |

---

## 4. What is and isn't implemented today

### ✅ Implemented and verified

- FastAPI app with ~20 HTTP endpoints
- SQLite persistence with auto-migration on column additions
- 3 strategies (RSI reversal, EMA breakout, VWAP pullback) computing indicators via pandas-ta
- Orchestrator pipeline with full persistence (Signal → Trade → AuditLog)
- Risk engine with 7 gates + Kelly-free position sizing capped at 1% per trade
- Paper broker with slippage simulation (no fees)
- Angel One live integration: TOTP login, scrip-master token resolution, live candle fetch, live order placement
- Intraday scheduler with market-hours awareness, parallel fetching, mark-to-market, and 15:20 EOD square-off
- OpenRouter LLM validation with SQL-backed memory context and daily spend cap
- Pretty human-readable console logs plus JSON mode for prod
- 47 pytest tests covering strategies, risk, Angel mocks, orchestrator persistence, scheduler hours, config API, and Phase 1 parallelism

### ⚠️ Built but not wired

- `regime_detector` — classifies regime but `SignalAgent` doesn't use it yet (Phase 3)
- `Position` table — exists but nothing writes to it (Phase 2 reconciliation)
- `kite_client` — broker impl exists, not exercised by any tests or current config

### ❌ Not yet built (roadmap items, see plan.md)

- Order status polling / partial-fill detection (Phase 2)
- Startup reconciliation against Angel positionBook (Phase 2)
- Bracket/cover orders — entry + SL are two separate calls today (Phase 2)
- Retry + circuit breaker on Angel calls (Phase 2)
- Telegram / email alerts (Phase 2)
- Fees in paper broker (Phase 2)
- Backtester (Phase 3)
- Parameter optimization (Phase 3)
- Multi-timeframe confirmation (Phase 3)
- Options chain / strike selection / Greeks (deferred to Phase 5)
- A/B test harness for LLM impact (Phase 4)
- NSE holiday calendar — bot will currently try to trade on Republic Day (any weekday holiday)

---

## 5. How a single trade flows from tick to DB

1. **09:15:00 IST** — Scheduler wakes for Tick #1.
2. **09:15:01** — `asyncio.gather()` launches 8 parallel candle fetches against Angel.
3. **09:15:02** — All 8 DataFrames arrive (~1s total). Log: `Fetched 8/8 symbols in 1047ms`.
4. **09:15:02** — ExecutionAgent.mark_to_market scans OPEN trades vs latest prices; none today → skip.
5. **09:15:02** — Not past 15:20 → skip square-off.
6. **09:15:02** — Pipeline runs per symbol. For NIFTY: RSIReversal sees RSI=28 → emits BUY signal (entry=24358, SL=24320, target=24420).
7. **09:15:02** — ValidationAgent: OpenRouter disabled (`.env` has `OPENROUTER_ENABLED=false`) → returns Validation(approved=True, confidence=0.65, source="disabled") because strategy confidence (0.73) ≥ fallback threshold (0.2).
8. **09:15:02** — Signal row INSERTed with `ai_confidence=0.65, ai_source=disabled`.
9. **09:15:02** — RiskEngine: no kill switch, 0/10 trades today, 0/5 open, daily loss OK, not expiry day, qty=75 (1 lot), risk = 75 × 38 = ₹2850… BUT `MAX_RISK_PER_TRADE_PCT=1%` of ₹25k = ₹250 → rejected. OR if SL is tighter, say entry=24358/SL=24355 → risk = 75 × 3 = ₹225 → approved. **(This gate is why lot-based F&O on ₹25k capital is always tight; Phase 3 Kelly work addresses this.)**
10. **09:15:02** — ExecutionAgent.execute: PaperBroker fills at 24358.10 (slippage +0.10). Trade row INSERTed status=OPEN. AuditLog row `trade_opened`.
11. **09:15:02** — Log: `[+] TRADE OPENED id=13 BUY 75 NIFTY @ 24358.10 ordId=PAPER-abc`.
12. **09:16:00** — Tick #2. Same flow. If NIFTY already has OPEN trade, scheduler logs `Skipping NIFTY — already in an open trade` and moves on.
13. **Later, say 11:27:00** — Tick #132. NIFTY price drops to 24319. Mark-to-market detects 24319 ≤ SL(24320) → closes trade. PnL = (24319 - 24358.10) × 75 = **-₹2932.50**. AuditLog `trade_auto_closed`. Daily realized_pnl = -2932.50 → getting close to daily loss cap of ₹500 → next signals may be risk-rejected until reset.
14. **15:20:00** — If any OPEN trades remain, ExecutionAgent.force_close_all() squares them off at latest price.

---

## 6. Configuration: what each `.env` key does

| Key | Purpose |
|---|---|
| `MODE` / `BROKER` / `PAPER_TRADE` | Paper vs live mode. `PAPER_TRADE=true` forces simulation even if broker=angel (safety belt). |
| `ENABLED_STRATEGIES` | Comma list of strategies to run. Leave one out to disable it. |
| `OPENROUTER_ENABLED` / `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | LLM toggle + model. |
| `AI_FALLBACK_APPROVE_THRESHOLD` | When LLM off, approve if strategy confidence ≥ this. Currently 0.2 (permissive). |
| `CAPITAL_INR` / `MAX_RISK_PER_TRADE_PCT` / `MAX_DAILY_LOSS_PCT` / `MAX_OPEN_POSITIONS` / `MAX_TRADES_PER_DAY` | Risk engine knobs. |
| `KILL_SWITCH` | Master stop. `true` → no new trades. Override via `POST /admin/killswitch/on`. |
| `AUTO_RUN_ENABLED` | Start scheduler automatically on app boot. |
| `WATCHLIST` | 8 symbols currently (NIFTY, BANKNIFTY, FINNIFTY, RELIANCE, HDFCBANK, TCS, INFY, ICICIBANK). |
| `RUN_INTERVAL_SEC` / `RUN_CANDLE_INTERVAL` | Tick cadence + candle size fed to strategies. |
| `MARKET_OPEN` / `MARKET_CLOSE` / `SQUARE_OFF_TIME` | IST wall-clock windows. |
| `LOG_FORMAT` | `pretty` (default, human console) or `json` (prod/ship to log aggregator). |
| `ANGEL_*` | Live credentials. `ANGEL_TOTP_SECRET` is base32 from the Angel app's QR code. |

---

## 7. How to run it

```powershell
# Activate venv (Windows)
.venv\Scripts\Activate.ps1

# Run tests
python -m pytest -q

# Start the server (scheduler auto-starts at boot if AUTO_RUN_ENABLED=true)
python app/main.py

# During market hours you'll see live ticks:
#   [09:15:01 INFO ] >> Tick #1  running pipeline for ['NIFTY:NSE', ..., 'ICICIBANK:NSE']
#   [09:15:02 INFO ]    Fetched 8/8 symbols in 1047ms
#   [09:15:02 INFO ]    [+] TRADE OPENED  id=13 BUY 75 NIFTY @ 24358.10  ordId=PAPER-abc

# Outside market hours (like Sunday evening) you'll see heartbeat:
#   [17:35:00 INFO ] -- Market CLOSED  (Sun 2026-04-19 17:35:00 IST)  -- next open: Mon 20 Apr 09:15 IST (in 15h 40m)
```

Key admin URLs once the server is up (default http://127.0.0.1:8000):
- `GET /health` — are we alive?
- `GET /runner/status` — tick count, trades opened today, last error
- `GET /report/today` — EOD PnL summary
- `GET /docs` — Swagger UI for every endpoint

---

## 8. Known footguns

1. **Holidays** — scheduler treats Mon-Fri as market days. It will happily try to trade on Republic Day, Diwali, etc. Fix before any live flip.
2. **Signal risk-rejection is common** — lot-based F&O on a ₹25k account with 1% risk per trade means many signals can't be sized (risk per trade exceeds ₹250 when the SL distance × 1 lot > ₹250). Either bump capital or use per-strategy tighter stops. Phase 3 Kelly sizing helps.
3. **No partial-fill handling** — live Angel orders are assumed to fill fully. If they partial-fill or reject, the bot's DB view diverges from reality. Fix in Phase 2.
4. **Entry vs SL race window** — entry order placed first, then SL order. If SL fails or is slow, you're briefly exposed. Phase 2 bracket orders close this.
5. **Strategy re-entry** — scheduler skips a symbol if any OPEN trade exists. A losing trade that auto-closes at SL frees the symbol up for a new entry on the same tick — this is intentional for mean-reversion but can whipsaw in trends.

---

See [plan.md](plan.md) for the detailed phased roadmap forward.
