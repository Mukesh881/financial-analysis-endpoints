# Agent-Ready Financial Data Tools — Design

Date: 2026-10-25
Status: Approved (trimmed, "ponytail" scope)

## Intent

The repo is four standalone FastAPI scripts wrapping yfinance (quote, price
history, company profile, analysis). Their primary consumer is now **LLM
agents calling them as tools**. An agent needs: a tool description that makes
it pick the right tool, error messages it can act on, and small outputs that
fit its context budget. The existing code also has correctness bugs.

## Goals

1. One package, shared core, the four scripts removed.
2. Two thin front doors over the same core: one FastAPI app (one port) and one
   MCP server.
3. Fix the bugs below, each with a regression test.
4. Agent-oriented outputs: multi-symbol quotes, downsampled history, compact
   profile, analysis with RSI/MACD/ATR and factual signals.

## Non-goals (trimmed on purpose)

No compare tool, no Bollinger/EMA extras, no Dockerfile, no CI, no new data
providers, no auth/rate-limiting, no third-party cache library, no backward
compatibility with the old routes.

## Bugs to fix

| # | Bug | Fix |
|---|-----|-----|
| 1 | `except Exception` swallows the code's own `HTTPException`s (end<start → 500; "no data" → "symbol not found"). | Typed errors in core; front doors map them. |
| 2 | Symbol validation rejects `BRK-B`, `^GSPC`, `EURUSD=X`, `BTC-USD`. | Regex `^[A-Z0-9^][A-Z0-9.\-=^]{0,14}$` after upper-casing. |
| 3 | Blocking yfinance in `async def` stalls the event loop. | Plain `def` handlers (FastAPI threadpool). |
| 4 | yfinance `end` is exclusive; last day dropped. | Core passes `end + 1 day`. |
| 5 | SMA-200 always null for short windows. | Analysis fetches a 300-calendar-day warm-up before `start`; returns measured on requested window. |
| 6 | `input()` in `__main__` hangs containers. | Removed; env vars for host/port. |
| 7 | Four apps on port 8000. | One app. |
| 8 | Volatility uses population std. | Sample std, annualised √252. |
| 9 | Unknown symbol's near-empty `ticker.info` treated as success. | No name/quote type ⇒ not found. |

## Layout

```
finapi/
  core.py        errors, validation, cached yfinance fetchers, indicators,
                 service functions returning Pydantic models
  rest.py        FastAPI app, /v1 routes, error mapping, /health
  mcp_server.py  MCP tools wrapping core (stdio default)
tests/test_core.py, tests/test_rest.py   offline, fake provider
pyproject.toml   deps + console scripts finapi-rest, finapi-mcp
```

The only yfinance access is through two small functions in `core.py`
(`_fetch_history`, `_fetch_info`) that tests monkeypatch.

## Tools (same on REST and MCP)

| Tool · route | Inputs | Output |
|---|---|---|
| `get_quotes` · `GET /v1/quotes?symbols=AAPL,MSFT` | 1–10 symbols | price, change %, day open/high/low, volume, prev close, currency, market state; per-symbol `error` instead of failing the batch |
| `get_price_history` · `GET /v1/history/{symbol}` | `start_date`/`end_date` or `period` (default `1mo`), `interval` `1d`/`1wk`/`1mo`, `max_points` (default 100, 2–1000) | evenly downsampled bars (first/last kept), `points_total`, summary: first/last close, return %, high, low |
| `get_company_profile` · `GET /v1/company/{symbol}` | `include_officers` (false), `summary_chars` (600) | name, sector, industry, country, website, employees, market cap, currency, truncated summary |
| `analyze_stock` · `GET /v1/analysis/{symbol}` | dates or `period` (default `6mo`) | return %, annualised volatility %, max drawdown %, high/low, SMA-50/200, RSI-14, MACD(12,26,9) line/signal/histogram, ATR-14, `signals` list, `disclaimer` |

Field names carry units (`volatility_annualized_pct`). Signals are factual
(RSI 70/30, SMA-50 vs SMA-200, MACD vs signal, price vs SMA-50) and replace
the old narrative advice.

Errors: REST returns `{"error": {"type", "message"}}` with 400/404/502; MCP
tools raise, the SDK reports an `isError` result. Messages state what was wrong
and what is accepted.

Cache: a small stdlib dict-with-expiry in `core.py`: quotes/info 60 s,
history 15 min.

## Approaches considered

- **A. Shared core + REST + MCP (chosen by the user).**
- B. REST only with agent-tuned OpenAPI: every framework needs its own adapter.
- C. REST + `fastapi-mcp`: tool contracts locked to HTTP design, extra dependency.

## Calls made by the designer

Old routes removed; narrative advice replaced by signals + disclaimer; history
default 100 points; no intraday intervals; profile and quotes share one cached
`info` fetch.
