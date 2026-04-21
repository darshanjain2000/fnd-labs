import logging
import sys

import structlog

from app.config import get_settings

# Map structured event names → friendly one-line messages.
# If an event isn't here it falls back to the structlog default renderer.
_EVENT_FRIENDLY: dict[str, str] = {
    # Boot
    "broker_init":                  "Broker ready  ({broker}, paper={forced_by_flag})",
    # Scheduler lifecycle
    "scheduler_started":            ">> Scheduler STARTED  watching {watchlist}",
    "scheduler_loop_entry":         "   Scheduler loop is now alive",
    "scheduler_stopped":            "-- Scheduler STOPPED  after {ticks} ticks",
    "scheduler_outside_hours":      "-- Market CLOSED  ({now})  -- next open: {next_open}",
    "scheduler_tick_start":         ">> Tick #{tick}  running pipeline for {watchlist}",
    "scheduler_fetch_done":         "   Fetched {fetched}/{requested} symbols in {elapsed_ms}ms",
    "scheduler_fetch_staggered":     "   Fetching {symbols} symbols with {stagger_ms}ms stagger (rate-limit guard)",
    "scheduler_tick_done":          "   Tick done  symbols={symbols}  skipped={skipped}  auto-closed={closed}  total_ticks={total_ticks}",
    "scheduler_fetch_failed":       "!! Candle fetch FAILED for {symbol}: {error}",
    "scheduler_too_few_candles":    "!! Only {rows} candles for {symbol} -- skipping",
    "scheduler_skip_in_trade":      "   Skipping {symbol} -- already in an open trade",
    "scheduler_eod_square_off":     "** EOD SQUARE-OFF  closed {closed} trades",
    "scheduler_tick_failed":        "XX Tick CRASHED: {exc_info}",
    "scheduler_heartbeat":          "** LIVE  tick={tick}  open={open_positions}  trades_today={trades_today}  pnl={realized_pnl:.2f}  signals={signals_seen}  uptime={uptime}",
    # Angel
    "scrip_master_downloading":     "   Downloading Angel scrip master (~50MB)...",
    "scrip_master_downloaded":      "   Scrip master downloaded: {rows} instruments",
    "scrip_master_loaded_from_cache": "   Scrip master loaded from cache ({rows} rows)",
    "angel_session_started":        "   Logged into Angel as {client}",
    "angel_token_resolved_local":   "   Resolved {symbol} -> token {token} (scrip={matched})",
    "angel_candles_fetched":        "   Fetched {rows} {interval} candles for {symbol} (token={token})",
    # Pipeline stages
    "pipeline_stage_signals":       "   [{symbol}] {count} signal(s) from strategies",
    # LLM
    "llm_validating":               "   [{symbol}] LLM validating {strategy} {side} (conf={confidence:.2f})...",
    "llm_call_ok":                  "   LLM call ok  spend=${spend_usd:.4f} today",
    "llm_call_failed":              "!! LLM call FAILED: {error}",
    "llm_parse_failed":             "!! LLM response parse FAILED: {error}",
    "llm_daily_reset":              "   LLM daily spend reset  prev=${prev_usd:.4f}",
    "llm_spend_cap_degrade":        "!! LLM spend cap hit, using fallback: {error}",
    "llm_no_api_key_degrade":       "!! LLM: no API key set -- using confidence fallback",
    # Strategy / AI / risk
    "signal_rejected_by_ai":        "   [X] AI rejected  {symbol} {strategy} {side} conf={confidence:.2f}  --  {reasoning}",
    "signal_rejected_by_risk":      "   [X] Risk rejected  {symbol} {strategy} {side}  --  {reason}",
    # Phase 3: regime + HTF filtering
    "regime_detected":              "   [R] Regime  {symbol} -> {regime}",
    "strategy_skipped_regime":      "   [-] Skipped {strategy} (regime={regime}, symbol={symbol})",
    "signal_rejected_htf":          "   [X] HTF rejected  {symbol} {strategy} {side} (HTF EMA disagrees)",
    "kelly_fraction_updated":       "   [K] Kelly fraction -> {fraction:.2f}",
    # Backtester
    "backtest_started":             ">> Backtest started  {strategy}  {symbol}  {from_date} -> {to_date}",
    "backtest_done":                "   Backtest done  trades={trades}  pnl={pnl:.2f}  sharpe={sharpe:.3f}  win_rate={win_rate:.1%}",
    # Ensemble conviction
    "signal_dropped_low_confidence": "   [-] Dropped {symbol} {strategy} {side} (conf={confidence:.2f} < {threshold:.2f})",
    "ensemble_insufficient":        "   [X] No conviction  {symbol}  sides={side_counts}  need={required}",
    "ensemble_selected":            "   [*] Conviction  {symbol} {side}  {agreement}/{total} strategies  best={strategy} conf={confidence:.2f}",
    "signal_memory_merged":         "   [M] Signal memory  {symbol}  {current} new + buffer -> {buffered} merged (window={window})",
    "backtest_fetching_data":       ">> Fetching {symbol} candles from Angel  {exchange} {interval}  {from_date} -> {to_date}",
    # Optuna optimizer
    "optimize_fetching_real_data":  ">> Optimizer fetching {symbol} candles  {interval}  {from_date} -> {to_date}",
    "optimize_using_synthetic_data": "   Optimizer using synthetic data (no --symbol/--from/--to)",
    # Optimized params
    "optimized_params_loaded":      "   [P] Optimized params loaded for {symbol}  strategies={strategies}",
    "optimized_params_load_failed": "!! Optimized params load FAILED for {symbol}: {error}",
    "strategy_loaded_optimized_params": "   [P] {symbol} {strategy} using optimized params: {params}",
    "strategy_optimized_params_invalid": "!! {symbol} {strategy} optimized params invalid ({error}) -- using defaults",
    # Execution
    "paper_order_filled":           "   [$] Paper fill  {side} {qty} {symbol} @ {price}  ({tag})",
    "execution_done":               "   [+] TRADE OPENED  id={trade_id} {side} {qty} {symbol} @ {fill}  ordId={order_id}",
    "trade_closed":                 "   [v] Trade {trade_id} CLOSED  pnl={pnl}",
    "trade_auto_closed":            "   [!] AUTO-CLOSE  trade {trade_id} {symbol} {side} @ {exit_price}  pnl={pnl}  ({reason})",
    "trade_force_closed":           "   [=] SQUARE-OFF  trade {trade_id} @ {exit_price}  pnl={pnl}",
}


def _friendly_renderer(logger, method_name, event_dict):
    """Custom structlog renderer: print human-readable line for known events,
    fall back to JSON-ish for unknown ones. Keeps level + timestamp prefix.
    """
    event = event_dict.get("event", "")
    level = event_dict.get("level", method_name).upper()
    ts = event_dict.pop("timestamp", "")
    # Drop keys that are part of the prefix so .format() doesn't see them
    event_dict.pop("level", None)
    payload = {k: v for k, v in event_dict.items() if k != "event"}

    template = _EVENT_FRIENDLY.get(event)
    if template:
        try:
            body = template.format(**payload)
        except (KeyError, IndexError, ValueError):
            # Missing key → show the raw event + payload instead of crashing
            body = f"{event}  {payload}"
    else:
        # Unknown event: still readable, not JSON
        body = f"{event}  " + "  ".join(f"{k}={v}" for k, v in payload.items())

    short_ts = ts.split("T")[1][:8] if "T" in ts else ts
    return f"[{short_ts} {level:5s}] {body}"


def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Best-effort: switch Windows console to UTF-8 so emoji / unicode don't crash.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, Exception):  # pragma: no cover
        pass

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    # Choose renderer based on LOG_FORMAT setting ("pretty" default, or "json" for prod)
    use_pretty = getattr(settings, "log_format", "pretty").lower() == "pretty"
    renderer = _friendly_renderer if use_pretty else structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
