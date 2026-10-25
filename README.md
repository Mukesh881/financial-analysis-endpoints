# Financial Data Tools for LLM Agents

Market data from Yahoo Finance (via `yfinance`), packaged as **four tools** that LLM agents can
call over **MCP** or **REST**. Both front doors wrap the same core, so they behave identically.

| Tool | REST route | What it returns |
|---|---|---|
| `get_quotes` | `GET /v1/quotes?symbols=AAPL,MSFT` | Latest price, % change, day range, volume for 1–10 symbols (bad symbols get a per-item `error`) |
| `get_price_history` | `GET /v1/history/{symbol}` | OHLCV bars downsampled to `max_points` (default 100) plus a summary: first/last close, return %, high, low |
| `get_company_profile` | `GET /v1/company/{symbol}` | Name, sector, industry, country, employees, market cap, truncated business summary; officers on request |
| `analyze_stock` | `GET /v1/analysis/{symbol}` | Return %, annualized volatility %, max drawdown %, SMA-50/200, RSI-14, MACD(12,26,9), ATR-14, plain-language signals |

**Inputs.** Symbols are Yahoo tickers: `AAPL`, `BRK-B`, `^GSPC`, `EURUSD=X`, `BTC-USD`,
`RELIANCE.NS`, `M&M.NS`. Windows are `start_date`/`end_date` (`YYYY-MM-DD`, inclusive; `end_date` defaults
to today) **or** `period` (`5d 1mo 3mo 6mo 1y 2y 5y 10y ytd max`). History intervals: `1d 1wk 1mo`.

**Errors** are written for the model to act on. REST returns
`{"error": {"type": "invalid_input" | "not_found" | "upstream_error", "message": "..."}}` with
400 / 404 / 502. MCP returns an `isError` tool result carrying the same message.

## Why it's shaped this way for agents

- **Small outputs by default.** History is downsampled and summarised, profiles are truncated, and
  officers are opt-in, so a tool call doesn't eat the context window.
- **Full precision for small prices.** FX rates and sub-cent crypto keep ~6 significant
  figures (`1.08563`, `0.0000123`); percentages are rounded to 2 decimals.
- **Units in field names** (`volatility_annualized_pct`, `max_drawdown_pct`) so the model doesn't
  guess.
- **Factual signals, not advice.** E.g. `"RSI-14 is 74.2: overbought zone (>= 70)."`, plus a fixed
  disclaimer field.
- **Caching.** An in-process cache (quotes/profiles 60 s, history 15 min) absorbs the repeated
  calls agents make within a conversation and eases Yahoo rate limits.

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
```

## Run as an MCP server

```bash
finapi-mcp                              # stdio (for Claude Desktop / Claude Code / IDEs)
finapi-mcp --transport streamable-http  # HTTP at http://127.0.0.1:8001/mcp (--host/--port,
                                        # or FINAPI_MCP_HOST / FINAPI_MCP_PORT)
```

Claude Code: `claude mcp add finapi -- /path/to/.venv/bin/finapi-mcp`

Claude Desktop (`claude_desktop_config.json`), or any client using the same format:

```json
{
  "mcpServers": {
    "finapi": { "command": "/path/to/.venv/bin/finapi-mcp" }
  }
}
```

Agent frameworks with MCP client support (LangGraph via `langchain-mcp-adapters`, NVIDIA NeMo
Agent Toolkit, OpenAI Agents SDK, etc.) can connect to either transport.

## Run as a REST API

```bash
finapi-rest   # FINAPI_HOST (default 127.0.0.1), FINAPI_PORT (default 8000)
curl 'http://127.0.0.1:8000/v1/analysis/AAPL?period=1y'
```

Interactive docs are at `/docs`. Each route's OpenAPI `operationId` is the tool name, so
OpenAPI-based tool loaders get the same names as MCP.

## Development

```bash
pytest        # offline: yfinance is replaced by a fake in tests/conftest.py
ruff check .
```

Layout: `finapi/core.py` (validation, cached data access, indicators, tool functions),
`finapi/rest.py`, `finapi/mcp_server.py`. All yfinance access goes through
`core._fetch_history` / `core._fetch_info`, the single place to add another data source.

## Changes from v1

v1 was four separate scripts that all bound to port 8000. Fixed along the way:

- Validation errors (e.g. end date before start date) returned 500, and "no data in range" was
  reported as "symbol not found".
- Valid tickers such as `BRK-B`, `^GSPC` and `EURUSD=X` were rejected.
- Blocking yfinance calls ran inside `async` handlers and stalled the server.
- The requested end date was silently excluded.
- SMA-200 was always empty for windows shorter than ~10 months; analysis now uses a warm-up period.
- Volatility used population rather than sample standard deviation.
- Unknown symbols returned an empty profile instead of 404.
- `input()` prompts at startup hung containers.

*Informational metrics only, not investment advice.*
