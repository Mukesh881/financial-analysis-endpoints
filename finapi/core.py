"""Shared core: errors, validation, market data access, indicators and the tool functions.

REST (`finapi.rest`) and MCP (`finapi.mcp_server`) are thin wrappers over this module.
"""

import math
import re
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd


class FinApiError(Exception):
    type = "error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidInputError(FinApiError):
    type = "invalid_input"


class NotFoundError(FinApiError):
    type = "not_found"


class UpstreamError(FinApiError):
    type = "upstream_error"


# --- validation -------------------------------------------------------------------------

_SYMBOL_RE = re.compile(r"^[A-Z0-9^][A-Z0-9.\-=^]{0,14}$")
MAX_SYMBOLS = 10
PERIOD_DAYS = {"5d": 7, "1mo": 31, "3mo": 92, "6mo": 183, "1y": 366, "2y": 731, "5y": 1827,
               "10y": 3653}
PERIODS = [*PERIOD_DAYS, "ytd", "max"]


def normalize_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not _SYMBOL_RE.match(s):
        raise InvalidInputError(
            f"Invalid symbol {symbol!r}. Use a Yahoo Finance ticker such as AAPL, BRK-B, "
            "^GSPC (index), EURUSD=X (FX), BTC-USD (crypto) or RELIANCE.NS (exchange suffix)."
        )
    return s


def normalize_symbols(symbols: str | list[str]) -> list[str]:
    if isinstance(symbols, str):
        symbols = symbols.split(",")
    out = list(dict.fromkeys(normalize_symbol(s) for s in symbols if s.strip()))
    if not out:
        raise InvalidInputError("Provide at least one symbol, e.g. AAPL or AAPL,MSFT.")
    if len(out) > MAX_SYMBOLS:
        raise InvalidInputError(f"At most {MAX_SYMBOLS} symbols per call; got {len(out)}.")
    return out


def _parse_date(value: str, name: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise InvalidInputError(f"{name} must be YYYY-MM-DD; got {value!r}.") from None


def resolve_window(start_date: str | None, end_date: str | None, period: str | None,
                   default_period: str) -> tuple[date | None, date]:
    """Return the inclusive (start, end) window; start is None for period 'max'."""
    today = date.today()
    if start_date or end_date:
        if period:
            raise InvalidInputError("Give either start_date/end_date or period, not both.")
        if not start_date:
            raise InvalidInputError("start_date is required when end_date is given.")
        start = _parse_date(start_date, "start_date")
        end = min(_parse_date(end_date, "end_date"), today) if end_date else today
        if end < start:
            raise InvalidInputError(f"end_date {end} is before start_date {start}.")
        return start, end
    period = period or default_period
    if period == "max":
        return None, today
    if period == "ytd":
        return date(today.year, 1, 1), today
    if period not in PERIOD_DAYS:
        raise InvalidInputError(f"Unknown period {period!r}. Use one of: {', '.join(PERIODS)}.")
    return today - timedelta(days=PERIOD_DAYS[period]), today


# --- indicators -------------------------------------------------------------------------

def _r(value, digits: int = 2) -> float | None:
    """Round to plain float; NaN/inf/None become None so output is always JSON-safe."""
    if value is None:
        return None
    value = float(value)
    return round(value, digits) if math.isfinite(value) else None


def _wilder(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(alpha=1 / n, adjust=False).mean()


def sma(close: pd.Series, n: int) -> float | None:
    return _r(close.iloc[-n:].mean()) if len(close) >= n else None


def rsi(close: pd.Series, n: int = 14) -> float | None:
    if len(close) <= n:
        return None
    diff = close.diff().dropna()
    gain = _wilder(diff.clip(lower=0), n).iloc[-1]
    loss = _wilder(-diff.clip(upper=0), n).iloc[-1]
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return _r(100 - 100 / (1 + gain / loss))


def macd(close: pd.Series) -> tuple[float, float, float] | None:
    if len(close) < 35:
        return None
    line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    signal = line.ewm(span=9, adjust=False).mean()
    return _r(line.iloc[-1]), _r(signal.iloc[-1]), _r(line.iloc[-1] - signal.iloc[-1])


def atr(df: pd.DataFrame, n: int = 14) -> float | None:
    if len(df) <= n:
        return None
    prev = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - prev).abs(), (df["Low"] - prev).abs()],
                   axis=1).max(axis=1)
    return _r(_wilder(tr, n).iloc[-1])


def annualized_volatility_pct(close: pd.Series) -> float | None:
    returns = close.pct_change().dropna()
    return _r(returns.std(ddof=1) * math.sqrt(252) * 100) if len(returns) >= 2 else None


def max_drawdown_pct(close: pd.Series) -> float | None:
    if close.empty:
        return None
    return _r(((close / close.cummax()) - 1).min() * 100)


def downsample(df: pd.DataFrame, max_points: int) -> pd.DataFrame:
    if len(df) <= max_points:
        return df
    positions = np.unique(np.linspace(0, len(df) - 1, max_points).round().astype(int))
    return df.iloc[positions]
