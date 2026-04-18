# trading-poc

AI-powered trading bot for Indian F&O (Zerodha Kite). Rule-based strategies validated by a Hybrid LLM layer (OpenRouter + local embeddings), gated by a strict Risk Engine.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # then fill in keys
```

## Run

```powershell
uvicorn app.main:app --reload
```

Endpoints:
- `GET  /`                — status + mode
- `GET  /health`
- `POST /analyze`         — run pipeline on supplied candles
- `POST /trade/manual`    — place a paper/live order
- `GET  /positions`       — in-memory risk stats
- `POST /killswitch/on`   — halt new orders
- `GET  /docs`            — Swagger UI

## Test

```powershell
pytest -q
```

## Layout

```
app/
├── agents/         signal, validation (LLM), execution
├── api/            FastAPI routers
├── core/           logging, market calendar
├── engine/         risk_engine (critical), regime_detector, orchestrator
├── models/         SQLAlchemy ORM
├── rag/            Chroma + sentence-transformers
├── services/       market_data, llm_client, broker (paper + kite)
├── strategies/     rsi_reversal, ema_breakout, vwap_pullback
├── config.py       pydantic-settings
├── db.py
└── main.py
tests/
```

## Modes

- `MODE=paper` — default. `PaperBroker` simulates fills against mock quotes.
- `MODE=live`  — `KiteBroker` (requires `KITE_API_KEY`, `KITE_ACCESS_TOKEN`).

## Safety

- Kill switch via `POST /killswitch/on`.
- Per-trade risk, daily loss cap, max trades/day, max open positions — all in [app/engine/risk_engine.py](app/engine/risk_engine.py).
- Expiry-day last-N-hours block (F&O).
- LLM validator **cannot override** risk rejections.

