# Agent-Ready Financial Data Tools — Design

Date: 2026-10-25
Status: Draft, awaiting approval

## Intent

The repo is four standalone FastAPI scripts wrapping yfinance (quote, price
history, company profile, analysis). Their primary consumer from now on is
**LLM agents calling them as tools**. For an agent, three things decide whether
a tool is useful: the model picks the right tool from its description, the
inputs it guesses are accepted (or rejected with a message it can act on), and
the output is small and unambiguous enough to fit the context budget.

Alongside that, the existing code has correctness bugs that must be fixed.

## Goals

1. One installable package with a shared core; the four scripts go away.
2. Two thin front doors over the same core:
   - **REST** (FastAPI): one app, one port, versioned routes, clean
     `operation_id`s and descriptions so OpenAPI-based tool loaders work.
   - **MCP server**: the same capabilities as MCP tools, usable from Claude,
     LangGraph, NVIDIA NeMo Agent Toolkit, and any MCP client.
3. Fix the known bugs (listed below).
4. Agent-oriented features: multi-symbol quotes, comparison, richer technical
   indicators, compact/downsampled outputs, caching.
5. Tests that run offline, plus packaging (pyproject, Dockerfile, CI).

## Non-goals

- New data providers (yfinance stays the only source; the data layer is a
  single module so another provider can be added later).
- Auth, rate limiting, persistence, or a distributed cache.
- Backward compatibility with the old routes and response shapes (no known
  callers; see Calls).
- Trading advice. Output is factual metrics and rule-based signals.

## Anti-goals

- Tools that return huge payloads by default (full multi-year daily OHLCV
  dumps) and blow an agent's context.
- Error messages an agent cannot act on ("Error: 500").
- REST and MCP drifting apart in behaviour: all logic lives in the core.

## Bugs to fix

| # | Bug | Fix |
|---|-----|-----|
| 1 | Blanket `except Exception` swallows the code's own `HTTPException`s: end<start returns 500; "no data in range" becomes "symbol not found". | Typed domain errors in the core; front doors map them. No string-sniffing for "404". |
| 2 | `validate_symbol` rejects valid tickers: `BRK-B`, `^GSPC`, `EURUSD=X`, `BTC-USD`. | Regex allowing `A-Z 0-9 . - = ^`, 1–15 chars, normalised to upper case. |
| 3 | Blocking yfinance calls inside `async def` stall the event loop. | Core is synchronous; REST handlers are plain `def` (FastAPI runs them in its threadpool); multi-symbol fetches use a bounded thread pool. |
| 4 | yfinance `end` is exclusive, silently dropping the requested last day. | Core treats `end_date` as inclusive (passes `end + 1 day`). |
| 5 | SMA-200 is always null for ranges under ~200 trading days (default 90). | Analysis fetches a lookback buffer before `start_date` for indicator warm-up; returns are still measured over the requested window. |
| 6 | `input()` in `__main__` hangs containers. | Removed; entry points read config from env vars. |
| 7 | Four apps all bind port 8000. | One REST app. |
| 8 | Volatility uses population std (`np.std`). | Sample std (`ddof=1`), annualised by √252. |
| 9 | Company profile: `ticker.info` returns `{}`/near-empty for unknown symbols and is treated as success. | Missing name and quote type ⇒ `NotFoundError`. |

## Architecture

```
finapi/
  core/
    errors.py      InvalidInputError, NotFoundError, UpstreamError
    validation.py  symbol + date parsing/normalisation
    provider.py    the only module that imports yfinance; TTL-cached fetchers
    indicators.py  pure pandas: SMA, EMA, RSI, MACD, ATR, Bollinger, drawdown, volatility
    service.py     use-case functions: get_quotes, get_history, get_profile,
                   analyze, compare  → return Pydantic models
  models.py        Pydantic response models shared by both front doors
  rest.py          FastAPI app (/v1/...), error mapping, /health
  mcp_server.py    MCP tools wrapping service.py
  config.py        env-driven settings (host, port, cache TTLs, limits)
tests/             offline: provider is replaced by a fake
```

The provider is injected/replaceable so tests (and a future second data source)
never touch yfinance.

## Capabilities (same set on REST and MCP)

| Tool / route | Purpose | Key inputs | Output highlights |
|---|---|---|---|
| `get_quotes` · `GET /v1/quotes?symbols=AAPL,MSFT` | Latest price snapshot for 1–10 symbols | `symbols` | price, change %, day range, volume, prev close, currency, market state, `as_of`; per-symbol errors don't fail the batch |
| `get_price_history` · `GET /v1/history/{symbol}` | OHLCV series | `start_date`/`end_date` **or** `period` (`1mo`…`5y`, `ytd`, `max`), `interval` (`1d`,`1wk`,`1mo`), `max_points` (default 100) | Downsampled to ≤ `max_points` by evenly picking bars (first/last kept), plus a range summary (first/last close, return %, high/low) and `points_returned`/`points_total` |
| `get_company_profile` · `GET /v1/company/{symbol}` | Who the company is | `include_officers` (default false), `summary_chars` (default 600) | name, sector, industry, country, website, employees, market cap, key valuation fields, truncated business summary |
| `analyze_stock` · `GET /v1/analysis/{symbol}` | Technical snapshot over a window | `start_date`/`end_date` or `period` (default `6mo`) | return %, annualised volatility %, max drawdown %, SMA 20/50/200, EMA 12/26, RSI-14, MACD(12,26,9), ATR-14, Bollinger(20,2), 52-week-style high/low of the window, list of rule-based `signals`, one-line `summary` |
| `compare_stocks` · `GET /v1/compare?symbols=…` | Relative performance of 2–10 symbols | `period` (default `1y`) | per-symbol return %, volatility %, max drawdown %, ranked by return; correlation of daily returns |

All numeric fields carry units in the name (`volatility_annualized_pct`,
`max_drawdown_pct`) so the model does not have to guess.

### Agent-facing details

- **Tool descriptions** say when to use the tool, the accepted symbol formats
  (with examples like `^GSPC`, `BRK-B`, `EURUSD=X`), and the default window.
- **Errors**: REST returns `{"error": {"type": "...", "message": "..."}}` with
  400/404/502. MCP tools raise, which the SDK turns into an `isError` tool
  result carrying the message, so the agent can correct itself and retry.
  Messages say what was wrong *and* what is accepted.
- **Signals** replace the old free-text "investment considerations": a list of
  short factual statements (e.g. "RSI-14 is 74.2 — above 70 (overbought
  zone)", "SMA-50 above SMA-200 (golden-cross regime)"). The response includes
  a fixed `disclaimer` field.

## Caching

In-process TTL cache keyed by the provider call arguments: quotes 60 s, history
15 min, profiles 24 h (env-configurable). Agents frequently repeat the same
call within a conversation, and Yahoo rate-limits aggressively.

## Limits & validation

- Symbols: max 10 per batch, deduplicated, upper-cased.
- Dates: `YYYY-MM-DD`; `start ≤ end`; `end` not in the future (clamped to
  today); either explicit dates or `period`, not both.
- `max_points`: 2–1000.

## Packaging & ops

- `pyproject.toml` (Python ≥ 3.10) with deps: fastapi, uvicorn, yfinance,
  pandas, numpy, pydantic, mcp, cachetools. Dev: pytest, httpx, ruff.
- Console scripts: `finapi-rest` (uvicorn), `finapi-mcp` (stdio default;
  `--transport streamable-http` option).
- Dockerfile running the REST app; README rewritten with REST + MCP setup,
  including an MCP client config snippet.
- GitHub Actions: ruff + pytest on push/PR.

## Testing

- Indicators: unit tests against hand-computable synthetic series.
- Service: fake provider returning fixed DataFrames/info dicts; covers each
  bug in the table above as a regression test.
- REST: FastAPI `TestClient` for status codes and error shape.
- MCP: tool listing and one call per tool through the SDK's in-memory client,
  using the fake provider.

## Approaches considered

- **A. Shared core + REST + MCP front doors (chosen).** Tool descriptions and
  payload sizes tunable per consumer; about one extra small module.
- **B. REST only, OpenAPI tuned for agents.** Least code, but every agent
  framework needs its own adapter and output is fixed to REST shapes.
- **C. REST + auto-generated MCP (`fastapi-mcp`).** Near-zero extra code but
  tool contracts are locked to HTTP design and adds a fast-moving dependency.

Chosen by the user: A.

## Calls made by the designer (check these)

1. Old scripts and routes are **removed**, not kept as aliases.
2. The narrative "investment considerations" text is replaced by factual
   `signals` + `summary` + `disclaimer`.
3. History defaults to **100 points** with even downsampling.
4. Interval limited to daily/weekly/monthly (no intraday).
5. In-process cache only.

## Left to the builder

Exact module internals, signal thresholds beyond the standard ones (RSI 70/30,
price vs. Bollinger bands, SMA crossovers, MACD vs. signal line), Dockerfile
base image, and test fixture shapes.
