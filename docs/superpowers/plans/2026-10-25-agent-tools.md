# Agent-Ready Financial Data Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace four standalone yfinance scripts with one package exposing four agent-friendly tools over REST and MCP, fixing the nine known bugs.

**Architecture:** `finapi/core.py` holds errors, validation, the only yfinance access (`_fetch_history`, `_fetch_info`, TTL-cached), indicators and four service functions returning Pydantic models. `finapi/rest.py` (FastAPI) and `finapi/mcp_server.py` (MCP `MCPServer`) are thin wrappers.

**Tech Stack:** Python ≥3.10, FastAPI, yfinance, pandas, numpy, pydantic v2, mcp 2.x (`from mcp.server.mcpserver import MCPServer`, `ToolError`; tests use `mcp.Client(server)` in-process), pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-25-agent-tools-design.md`

## Global Constraints

- Symbol regex after `.strip().upper()`: `^[A-Z0-9^][A-Z0-9.\-=^]{0,14}$`; batch max 10, deduplicated, order preserved.
- Dates `YYYY-MM-DD`; `end_date` inclusive; future `end_date` clamped to today; dates and `period` are mutually exclusive.
- Periods: `5d 1mo 3mo 6mo 1y 2y 5y 10y ytd max`. Intervals: `1d 1wk 1mo`. `max_points` 2–1000, default 100.
- Cache TTL: info 60 s, history 900 s. Stdlib only.
- Field names carry units (`..._pct`). No NaN in output — use `None`.
- Error JSON (REST): `{"error": {"type": "invalid_input|not_found|upstream_error", "message": str}}` with 400/404/502.
- MCP tools must raise `ToolError(message)` for domain errors (other exceptions are hidden from the model in mcp 2.x).
- Analysis warm-up: fetch 300 calendar days before the window start.
- Disclaimer text: `"Informational metrics only, not investment advice."`
- No yfinance access in tests (monkeypatch `core._fetch_history` / `core._fetch_info`).

## Review Focus

1. Window containing no trading days (e.g. a weekend) → 404 `not_found` with a hint to widen the range, not 500. Test in Task 3.
2. yfinance rows containing NaN → `None` fields, response still serialises. Test in Task 3.
3. Symbols given as `"aapl, AAPL ,msft"` → `["AAPL", "MSFT"]`. Test in Task 1.
4. `max_points` ≥ rows returns all rows; `max_points=2` returns first and last. Test in Task 2.
5. yfinance raising a network error → 502 `upstream_error` / MCP `ToolError`, never a crash. Test in Task 4 and 5.

---

### Task 1: Package scaffold, errors, validation

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `finapi/__init__.py`, `finapi/core.py`, `tests/test_core.py`

**Interfaces:**
- Produces: `FinApiError(message)` with class attr `type: str`; subclasses `InvalidInputError` (`"invalid_input"`), `NotFoundError` (`"not_found"`), `UpstreamError` (`"upstream_error"`).
- `normalize_symbol(symbol: str) -> str`; `normalize_symbols(symbols: str | list[str]) -> list[str]` (comma-separated string allowed).
- `resolve_window(start_date: str | None, end_date: str | None, period: str | None, default_period: str) -> tuple[date | None, date]` — returns inclusive `(start, end)`; `start=None` means `max`. Period → days: `5d:7, 1mo:31, 3mo:92, 6mo:183, 1y:366, 2y:731, 5y:1827, 10y:3653`; `ytd` → Jan 1 of today's year.

- [ ] **Step 1: Write failing tests** `test_normalize_symbol_accepts_real_tickers` (`brk-b`→`BRK-B`, `^GSPC`, `EURUSD=X`, `BTC-USD`, `RELIANCE.NS`), `test_normalize_symbol_rejects` (`""`, `"AA PL"`, `"A;DROP"`, 16-char → `InvalidInputError`), `test_normalize_symbols_dedupes` (`"aapl, AAPL ,msft"` → `["AAPL","MSFT"]`; 11 symbols → error), `test_resolve_window` (explicit dates inclusive; end before start → error; bad format → error; dates+period → error; future end clamped to today; unknown period → error; `max` → start None).
- [ ] **Step 2:** `pytest tests/test_core.py -q` → FAIL (import error).
- [ ] **Step 3:** Implement in `finapi/core.py`. `pyproject.toml`: deps `fastapi, uvicorn, yfinance, pandas, numpy, pydantic>=2, mcp>=2,<3`; optional `dev = [pytest, httpx, ruff]`; scripts `finapi-rest = "finapi.rest:main"`, `finapi-mcp = "finapi.mcp_server:main"`. `.gitignore`: `.venv/ __pycache__/ *.egg-info/ .pytest_cache/ .ruff_cache/`.
- [ ] **Step 4:** tests PASS.
- [ ] **Step 5:** Commit `feat: add finapi package with validation and typed errors`.

### Task 2: Indicators and downsampling

**Files:** Modify `finapi/core.py`, `tests/test_core.py`

**Interfaces (all take pandas Series/DataFrame with `Open High Low Close Volume`, return `float | None`, None when too few points, rounded to 2 dp unless noted):**
- `sma(close, n)`, `rsi(close, n=14)` (Wilder smoothing via `ewm(alpha=1/n, adjust=False)`), `macd(close) -> tuple[float, float, float] | None` (line, signal, histogram; EMA 12/26/9, `adjust=False`; None if < 35 points), `atr(df, n=14)` (Wilder, true range), `annualized_volatility_pct(close)` (sample std of pct_change × √252 × 100), `max_drawdown_pct(close)` (negative or 0), `downsample(df, max_points) -> DataFrame` (evenly spaced integer positions via `numpy.linspace(0, len-1, max_points).round()`, unique, keeps first/last).

- [ ] **Step 1: Write failing tests**: `sma([1..10],5)==8.0`; `sma(short)` is None; `rsi` of strictly rising series == 100.0, falling == 0.0; `macd` of constant series == (0.0,0.0,0.0); `atr` of bars with high-low=2 and no gaps == 2.0; volatility of constant series == 0.0; `max_drawdown_pct([100,120,60,90]) == -50.0`; `downsample` of 10 rows to 2 → positions 0 and 9; to 50 → 10 rows.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat: add technical indicators and downsampling`.

### Task 3: Provider, cache and service functions

**Files:** Modify `finapi/core.py`; Create `tests/conftest.py`; Modify `tests/test_core.py`

**Interfaces:**
- `_fetch_history(symbol: str, start: date | None, end_exclusive: date, interval: str) -> pd.DataFrame` and `_fetch_info(symbol: str) -> dict` — the only yfinance callers. Wrapped by `_cached(key, ttl, fn)`; any non-`FinApiError` exception from yfinance → `UpstreamError("Market data provider failed for {symbol}: {exc}. Retry shortly.")`. Tests patch `_fetch_history`/`_fetch_info` and clear `core._CACHE`.
- Models (Pydantic): `Quote{symbol, name, currency, market_state, price, change_pct, open, day_high, day_low, volume, previous_close, error: str|None}`; `QuotesResponse{quotes: list[Quote]}`; `Bar{date, open, high, low, close, volume}`; `HistorySummary{first_close, last_close, return_pct, high, low}`; `HistoryResponse{symbol, interval, start, end, points_total, points_returned, summary, bars}`; `CompanyProfile{symbol, name, quote_type, sector, industry, country, website, employees, market_cap, currency, summary, officers: list[Officer]|None}`; `Officer{name, title}`; `Analysis{symbol, start, end, last_close, return_pct, volatility_annualized_pct, max_drawdown_pct, high, low, sma_50, sma_200, rsi_14, macd, macd_signal, macd_histogram, atr_14, signals: list[str], disclaimer}`.
- `get_quotes(symbols) -> QuotesResponse`; `get_price_history(symbol, start_date=None, end_date=None, period=None, interval="1d", max_points=100) -> HistoryResponse` (default period `1mo`); `get_company_profile(symbol, include_officers=False, summary_chars=600) -> CompanyProfile`; `analyze_stock(symbol, start_date=None, end_date=None, period=None) -> Analysis` (default `6mo`; indicators on warm-up+window; return/vol/drawdown/high/low on window only).
- Not found: empty history → `NotFoundError("No price data for {symbol} between {start} and {end}. Check the symbol or widen the date range.")`; info with none of `quoteType/longName/shortName` → `NotFoundError("Unknown symbol {symbol}. ...")`.
- Signals (only when inputs available): RSI ≥70 overbought / ≤30 oversold; SMA-50 above/below SMA-200; MACD above/below signal; last close above/below SMA-50.

- [ ] **Step 1: Write failing tests** with a `fake_market` fixture (252+ daily bars synthetic uptrend, info dict for AAPL): `test_history_end_date_inclusive` (fetch called with `end_exclusive = end + 1 day`), `test_history_downsamples_and_summarises`, `test_history_nan_row_becomes_none`, `test_history_empty_is_not_found` (message contains "widen"), `test_analysis_has_sma_200_for_short_window` (90-day window, warm-up start = window start − 300 days), `test_analysis_signals_and_disclaimer`, `test_quotes_per_symbol_error` (one unknown symbol → its `error` set, other ok), `test_profile_truncates_summary_and_hides_officers`, `test_unknown_info_is_not_found`, `test_provider_exception_becomes_upstream`, `test_info_cached` (two calls → one fetch).
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat: add cached provider and service functions`.

### Task 4: REST app

**Files:** Create `finapi/rest.py`, `tests/test_rest.py`

**Interfaces:** `app: FastAPI`; routes (plain `def`, `operation_id` = tool name): `GET /health`, `GET /v1/quotes?symbols=`, `GET /v1/history/{symbol}`, `GET /v1/company/{symbol}`, `GET /v1/analysis/{symbol}`. Exception handler maps `FinApiError` → status by type; FastAPI's `RequestValidationError` → 400 `invalid_input`. `main()` runs uvicorn on `FINAPI_HOST` (default `127.0.0.1`) / `FINAPI_PORT` (`8000`).

- [ ] **Step 1: Failing tests** (TestClient, `fake_market`): health 200; each route 200 with expected keys; bad symbol → 400 with error shape; end<start → 400 (bug 1 regression); unknown symbol → 404; provider exception → 502; `max_points=1` → 400.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat: add unified REST API`.

### Task 5: MCP server, cleanup, README

**Files:** Create `finapi/mcp_server.py`, `tests/test_mcp.py`; Delete the four `*_api1.py`; Modify `README.md`

**Interfaces:** `mcp = MCPServer("finapi", instructions=...)`; tools `get_quotes(symbols: list[str])`, `get_price_history(...)`, `get_company_profile(...)`, `analyze_stock(...)` with the same params/defaults as core, returning the core model's `model_dump()`; `FinApiError` → `ToolError(str(e))`. Docstrings say when to use the tool and give symbol examples (`AAPL`, `BRK-B`, `^GSPC`, `EURUSD=X`, `RELIANCE.NS`). `main()` parses `--transport {stdio,streamable-http}` (default stdio).

- [ ] **Step 1: Failing tests** (`async with Client(mcp)`, run via `asyncio.run`): lists exactly the four tools; `analyze_stock` returns `is_error=False` with `rsi_14`; unknown symbol → `is_error=True` and message text contains the symbol; provider exception → `is_error=True`.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS; `ruff check .` clean.
- [ ] **Step 5:** Delete old scripts; rewrite README (what it is, install, run REST, run MCP, Claude Desktop/Claude Code MCP config snippet, tool table, bug-fix notes).
- [ ] **Step 6:** Commit `feat: add MCP server, remove legacy scripts, rewrite README`.
