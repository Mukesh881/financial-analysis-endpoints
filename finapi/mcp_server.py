"""MCP front door: the same four tools as the REST API, for any MCP client."""

import argparse
import functools
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from finapi import core

SYMBOLS_HELP = ("Yahoo Finance tickers: AAPL, BRK-B, ^GSPC (index), EURUSD=X (FX), BTC-USD "
                "(crypto), RELIANCE.NS / VOD.L (non-US listings need the exchange suffix).")

mcp = MCPServer(
    "finapi",
    instructions="Market data from Yahoo Finance. " + SYMBOLS_HELP + " Dates are YYYY-MM-DD "
                 "and inclusive; pass either start_date/end_date or period, not both. "
                 "Outputs are informational, not investment advice.",
)

Period = Literal["5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"]


def _tool(fn):
    """Register fn as a tool; domain errors become ToolError so the model sees the message."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except core.FinApiError as exc:
            raise ToolError(exc.message) from exc
    return mcp.tool()(wrapper)


@_tool
def get_quotes(symbols: list[str]) -> core.QuotesResponse:
    """Latest price, % change vs previous close, day range and volume for 1-10 symbols.

    Use for "what is X trading at" questions. A bad symbol gets its own `error` field
    instead of failing the whole call.
    """
    return core.get_quotes(symbols)


@_tool
def get_price_history(symbol: str, start_date: str | None = None, end_date: str | None = None,
                      period: Period | None = None,
                      interval: Literal["1d", "1wk", "1mo"] = "1d",
                      max_points: int = 100) -> core.HistoryResponse:
    """OHLCV bars for one symbol plus a summary (first/last close, return %, high, low).

    Default window is 1mo. Bars are evenly downsampled to at most `max_points` (2-1000), keeping
    the first and last bar; `points_total` says how many existed. Prefer the summary, or
    analyze_stock, over requesting many points.
    """
    return core.get_price_history(symbol, start_date, end_date, period, interval, max_points)


@_tool
def get_company_profile(symbol: str, include_officers: bool = False,
                        summary_chars: int = 600) -> core.CompanyProfile:
    """Who a company or fund is: name, sector, industry, country, employees, market cap and a
    business summary truncated to `summary_chars` (0-5000). Officers only when asked."""
    return core.get_company_profile(symbol, include_officers, summary_chars)


@_tool
def analyze_stock(symbol: str, start_date: str | None = None, end_date: str | None = None,
                  period: Period | None = None) -> core.Analysis:
    """Technical snapshot over a window (default 6mo): return %, annualized volatility %, max
    drawdown %, high/low, SMA-50/200, RSI-14, MACD(12,26,9), ATR-14 and plain-language signals.

    Indicators use extra history before the window, so SMA-200 is available for short windows.
    """
    return core.analyze_stock(symbol, start_date, end_date, period)


def main():
    parser = argparse.ArgumentParser(description="Run the finapi MCP server.")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    mcp.run(transport=parser.parse_args().transport)


if __name__ == "__main__":
    main()
