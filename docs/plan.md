# Next-Phase Plan: POC → Production Trading Bot

Last updated: April 21, 2026 · Phase 1 complete, Phase 3 largely complete.

## TL;DR
POC works end-to-end (**102/102 tests**, live Angel data, pretty logs, EOD reports, 8-symbol watchlist with parallel fetch).
Next work splits into **4 phases**:
- **Phase 1 ✅ DONE** — Expand watchlist + parallelize fetches + persist AI confidence.
- **Phase 2** — Real-trade readiness: order reconciliation, startup position sync, bracket orders, retry/circuit breakers, alerting.
- **Phase 3 ✅ MOSTLY DONE** — 7 strategies (rsi_reversal, ema_breakout, vwap_pullback, supertrend, macd_divergence, bollinger_squeeze, orb_breakout), all indicators, backtester, Optuna optimizer (auto-loads `config/params_{symbol}.yaml`), ensemble conviction, Kelly sizing, regime filter, HTF agreement, signal memory. Walk-forward OOS + live HTF fetch pending.
- **Phase 4** — LLM impact measurement: A/B harness comparing Sonnet vs Haiku vs rules-only, per-signal cost tracking, shadow tracker for "would-have-been" PnL on rejected signals.

---

## Phase 1 — Quick Win ✅ COMPLETE

### Steps
1. ✅ `.env`: expanded WATCHLIST to 8 symbols (NIFTY, BANKNIFTY, FINNIFTY, RELIANCE, HDFCBANK, TCS, INFY, ICICIBANK). Bumped `MAX_OPEN_POSITIONS=5`, `MAX_TRADES_PER_DAY=10`.
2. ✅ Parallelized candle fetch in scheduler `_tick()` with `asyncio.gather(return_exceptions=True)`.
3. ✅ Persisted AI confidence + source: added `Signal.ai_confidence` and `Signal.ai_source` columns; orchestrator writes them.
4. ✅ Added skipped-counter and fetch elapsed_ms to tick summary log.
5. ✅ 47/47 pytest green (added 2 tests: parallel fetch <0.9s, signal persistence check).
6. ✅ SQLite auto-migration helper in `app/db.py` adds new columns to existing DBs on boot.

### Files changed
- `.env`
- `app/services/scheduler.py` — `_tick()` parallel fetch, skipped counter
- `app/models/trade.py` — Signal adds ai_confidence, ai_source
- `app/engine/orchestrator.py` — persists new fields
- `app/db.py` — `_apply_sqlite_additions()` migration helper
- `app/core/logging.py` — friendly templates for `scheduler_fetch_done` + updated `scheduler_tick_done`
- `tests/test_phase1.py` — new

### Verification (verified)
- Migration: `signals` table now has `ai_confidence, ai_source` columns.
- Parallel test: 4 × 300ms fetches complete in <0.9s (vs >1.1s serial).
- `pytest -q` → 47 passed.

---

## Phase 2 — Real-Trade Readiness (before live money)

### Steps
**2A. Order lifecycle** — New `OrderLog` model (PLACED/ACK/FILLED/PARTIAL/REJECTED). `app/services/order_poller.py` polls Angel `orderBook()` every 3s.
**2B. Startup reconciliation** — `reconcile_positions()` compares Angel `positionBook()` vs DB OPEN trades on boot.
**2C. Bracket orders** — investigate Angel bracket/cover API, eliminate entry↔SL race window.
**2D. Resilience** — `tenacity` retry + `pybreaker` circuit breaker on all Angel calls.
**2E. Alerting** — `app/services/notifier.py` with Telegram + SMTP hooks on trade open/close/SL/kill_switch/error.
**2F. Realistic paper model** — parametric slippage (index 2bps, stock 8bps), brokerage fees (₹40 RT), match live behavior.

### Relevant files
- `app/models/trade.py` — `OrderLog` model
- `app/services/order_poller.py`, `app/services/reconciler.py`, `app/services/notifier.py` — all new
- `app/services/broker/angel_client.py` — retry + bracket support
- `app/services/broker/paper_broker.py` — parametric slippage + fees
- `app/main.py` — lifespan calls reconciler
- `requirements.txt` — tenacity, pybreaker, python-telegram-bot

### Verification
- Unit tests: OrderPoller with mocked partial fills/rejections, reconciler mismatch detection, circuit breaker trips after 5 failures.
- 1-day paper run with new slippage+fee model, compare avg PnL vs old.
- Manual: 1-lot NIFTY live for 1 hour with `PAPER_TRADE=false`, verify complete OrderLog trail.

---

## Phase 3 — Better Strategies ✅ MOSTLY DONE

### Steps
**3A. Indicators** — add MACD, Bollinger, ADX, Supertrend, OBV, Stochastic to `compute_indicators`. Add HTF resampler (5m→15m+1h). **DONE**
- Indicators live in `app/services/market_data.py`: rsi, ema20, ema50, vwap, atr14, macd, macd_signal, macd_hist, bb_upper/mid/lower/width, stoch_k, stoch_d, obv, adx, supertrend, supertrend_dir.

**3B. New strategies** — `supertrend.py`, `macd_divergence.py`, `bollinger_squeeze.py`, `orb_breakout.py` (opening-range). **DONE**
- All 7 strategies live in `app/strategies/`: rsi_reversal, ema_breakout, vwap_pullback, supertrend, macd_divergence, bollinger_squeeze, orb_breakout.

**3C. Regime-aware routing** — wire `regime_detector` into `SignalAgent`. Per-strategy regime weights in config (`regime_filter_enabled`). **DONE**
- `app/engine/regime_detector.py` detects: trend_up, trend_down, range, high_vol.
- `Strategy.applies_to_regime()` in `app/strategies/base.py`.
- `SignalAgent` skips strategies not matching current regime.

**3D. Multi-timeframe confirm** — `require_htf_agreement` flag; EMA direction on 15m must match signal side. **DONE**
- Config: `require_htf_agreement` in `app/config.py`.
- `_htf_agrees()` in `app/agents/signal_agent.py`.

**3E. Ensemble conviction filter** — signal memory window, min-strategy agreement gate, confidence gate. **DONE**
- Config: `min_strategy_agreement`, `min_signal_confidence`, `signal_memory_ticks`.
- `select_best_signal()` and `_merge_with_buffer()` in `app/engine/orchestrator.py`.

**3F. Backtester** — `app/backtest/runner.py`. CLI: `python -m app.backtest.runner --symbol NIFTY --from 2025-01-01 --to 2025-04-01`. **DONE**

**3G. Optuna optimization** — `optimize_all.py` runs all 7 strategies for a symbol (default: last 5 years). Saves best params to `config/params_{symbol}.yaml`. The live pipeline auto-loads these. **DONE**
- Example: `python optimize_all.py --symbol NIFTY`
- Override date range or trials: `python optimize_all.py --symbol NIFTY --from 2024-01-01 --to 2025-01-01 --trials 50`
- Auto-loading: `app/core/optimized_params.py` + `SignalAgent` builds per-symbol strategy instances with optimized params.

**3H. Kelly sizing** — RiskEngine optional Kelly multiplier using last 20 trades' win_rate + avg_win/loss, capped at max_risk_pct. **DONE**
- `compute_kelly_fraction()` and `update_kelly_fraction()` in `app/engine/risk_engine.py`.
- Config: `kelly_sizing_enabled`.

### Remaining in Phase 3
- Walk-forward OOS validation (rolling train/test windows) — not yet implemented in `runner.py`.
- HTF candle resampler (5m→15m+1h) for live scheduler — plumbed in SignalAgent but not yet fetched in scheduler tick.

### Files changed (Phase 3)
- `app/services/market_data.py` — all indicators
- `app/strategies/` — 4 new strategy files + `base.py` `applies_to_regime()` hook
- `app/agents/signal_agent.py` — regime filter, HTF agreement, optimized params per symbol
- `app/engine/orchestrator.py` — ensemble conviction, signal memory buffer
- `app/engine/regime_detector.py` — regime detection
- `app/engine/risk_engine.py` — Kelly sizing
- `app/backtest/runner.py`, `app/backtest/optimize.py` — backtester + optimizer
- `app/core/optimized_params.py` — per-symbol params loader
- `optimize_all.py` — batch Optuna runner (default: last 5 years)
- `config/params_{symbol}.yaml` — generated by optimizer, auto-loaded at runtime
- `requirements.txt` — optuna

### Verification (verified)
- 102/102 pytest green.
- All 7 strategies tested in `tests/test_strategies.py`.
- Ensemble conviction tested in `tests/test_orchestrator_conviction.py`.
- Optimized params loader tested in `tests/test_optimized_params.py`.
- Backtests run successfully for NETWEB, HSCL, NIFTY.

---

## Phase 4 — Measuring OpenRouter Impact (THE experiment)

### Hypothesis
LLM rejects ~20-40% of signals. If rejected would-have-lost & approved win, LLM adds value. Else noise + cost (~$0.003/signal Sonnet, ~$0.0003 Haiku).

### Design
3 arms: **control (no LLM)**, **Sonnet**, **Haiku**. Compare win rate, avg PnL, Sharpe, rejection rate, $/trade, net value add.

### Steps
1. Config: `AB_TEST_MODE=off|shadow|split`. Shadow = run all models in parallel on every signal, execute first only.
2. `AIDecision` table: signal_id, model, approved, confidence, reasoning, tokens, cost_usd, latency_ms, realized_pnl, hypothetical_pnl.
3. `LLMClient` returns `LLMResponse(content, usage, cost_usd, latency_ms)` (not raw dict).
4. `Trade.ai_decision_id` FK; backfill `realized_pnl` on trade close.
5. **Shadow tracker** (`app/services/shadow_tracker.py`) — for REJECTED signals, watch next 20 candles, record "would-have-been" PnL assuming same SL/target. Critical for attribution.
6. New endpoint `GET /report/ab_test` → per-model: n_signals, n_approved, avg_pnl_approved, avg_hypo_pnl_rejected, cost, **net_value_add**.
7. Run shadow mode for 4 weeks paper → collect 500-1000 signals → two-sample t-test on PnL distributions.
8. **Decision rule**: Sonnet net_value_add > 0 AND p<0.05 → enable LLM for live. Else rules-only.

### Relevant files
- `app/config.py` — `AB_TEST_MODE`, `AB_MODELS`, `AB_TEST_SPLIT`
- `app/models/trade.py` — `AIDecision`, `Trade.ai_decision_id`
- `app/agents/validation_agent.py` — shadow mode, `override_model` param
- `app/services/llm_client.py` — `LLMResponse` with cost+latency
- `app/services/shadow_tracker.py` — new
- `app/api/report.py` — `/report/ab_test`
- `scripts/analyze_ab.py` — offline stats

### Verification
- Shadow mode: N `AIDecision` rows per signal, only first model's decision drives execution.
- Shadow tracker finds SL/target hit in next 20 candles for rejected signal.
- 4-week paper run → `/report/ab_test` returns meaningful numbers with statistical test.

---

## Decisions
- Paper→live gated on Phase 2 complete + 2 weeks clean paper with new watchlist.
- LLM stays ON during Phase 3 backtesting.
- SQLite stays until Phase 4 heavy decision logging.
- Options / strikes / Greeks — **explicitly excluded** (Phase 5 if futures prove profitable).

## Further Considerations
1. LLM cost trivial: 8 symbols × 10 signals/day × $0.003 = $0.24/day Sonnet. Run both Sonnet + Haiku in shadow.
2. Capital scaling: ₹25k → ₹1L for Phase 5 live if Phase 4 shows positive EV.
3. **NSE holiday calendar** — scheduler hardcodes Mon-Fri. Add `nsepy.get_holidays()` before live flip or bot trades on Republic Day.

## Recommended order
1. ✅ Phase 1 DONE.
2. ✅ Phase 3 MOSTLY DONE — strategies, backtester, optimizer, ensemble conviction, Kelly sizing, auto-loaded params.
3. **Phase 3 remaining** — walk-forward OOS validation, live HTF candle fetch in scheduler.
4. **Phase 2 NEXT** — real-trade readiness before any live money (order reconciliation, alerting, circuit breakers).
5. **Phase 4 AFTER** — 4 weeks paper shadow for LLM A/B measurement.
6. **Phase 5 LIVE** — only if Phase 2 done + Phase 4 positive EV.
