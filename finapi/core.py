"""Shared core: errors, validation, market data access, indicators and the tool functions.

REST (`finapi.rest`) and MCP (`finapi.mcp_server`) are thin wrappers over this module.
"""

import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf
from pydantic import BaseModel


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
INTERVALS = ("1d", "1wk", "1mo")
WARMUP_DAYS = 300
INFO_TTL, HISTORY_TTL = 60, 900
DISCLAIMER = "Informational metrics only, not investment advice."


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


# --- market data (the only yfinance access; tests replace the two _fetch_* functions) ---

_CACHE: dict = {}


def _fetch_history(symbol: str, start: date | None, end_exclusive: date,
                   interval: str) -> pd.DataFrame:
    ticker = yf.Ticker(symbol)
    if start is None:
        return ticker.history(period="max", interval=interval)
    return ticker.history(start=start.isoformat(), end=end_exclusive.isoformat(),
                          interval=interval)


def _fetch_info(symbol: str) -> dict:
    return yf.Ticker(symbol).info or {}


def _cached(key: tuple, ttl: int, fn):
    hit = _CACHE.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    try:
        value = fn()
    except FinApiError:
        raise
    except Exception as exc:
        raise UpstreamError(
            f"Market data provider failed for {key[1]}: {exc}. Retry shortly.") from exc
    _CACHE[key] = (time.monotonic() + ttl, value)
    return value


def _info(symbol: str) -> dict:
    info = _cached(("info", symbol), INFO_TTL, lambda: _fetch_info(symbol))
    if not (info.get("longName") or info.get("shortName")
            or info.get("quoteType") not in (None, "NONE")):
        raise NotFoundError(
            f"Unknown symbol {symbol}. Check the ticker; non-US listings need an exchange "
            "suffix such as .NS, .L or .T.")
    return info


def _history(symbol: str, start: date | None, end: date, interval: str) -> pd.DataFrame:
    """Bars for the inclusive window [start, end]. yfinance's `end` is exclusive, hence +1 day."""
    end_exclusive = end + timedelta(days=1)
    df = _cached(("history", symbol, start, end_exclusive, interval), HISTORY_TTL,
                 lambda: _fetch_history(symbol, start, end_exclusive, interval))
    if df is None or df.empty or df["Close"].dropna().empty:
        raise NotFoundError(
            f"No price data for {symbol} between {start or 'listing'} and {end}. Check the "
            "symbol or widen the date range (markets are closed on weekends and holidays).")
    return df


# --- response models --------------------------------------------------------------------

class Quote(BaseModel):
    symbol: str
    name: str | None = None
    currency: str | None = None
    market_state: str | None = None
    price: float | None = None
    change_pct: float | None = None
    open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    volume: int | None = None
    previous_close: float | None = None
    error: str | None = None


class QuotesResponse(BaseModel):
    quotes: list[Quote]


class Bar(BaseModel):
    date: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None


class HistorySummary(BaseModel):
    first_close: float | None
    last_close: float | None
    return_pct: float | None
    high: float | None
    low: float | None


class HistoryResponse(BaseModel):
    symbol: str
    interval: str
    start: str
    end: str
    points_total: int
    points_returned: int
    summary: HistorySummary
    bars: list[Bar]


class Officer(BaseModel):
    name: str | None
    title: str | None


class CompanyProfile(BaseModel):
    symbol: str
    name: str | None
    quote_type: str | None
    sector: str | None
    industry: str | None
    country: str | None
    website: str | None
    employees: int | None
    market_cap: float | None
    currency: str | None
    summary: str | None
    officers: list[Officer] | None = None


class Analysis(BaseModel):
    symbol: str
    start: str
    end: str
    last_close: float | None
    return_pct: float | None
    volatility_annualized_pct: float | None
    max_drawdown_pct: float | None
    high: float | None
    low: float | None
    sma_50: float | None
    sma_200: float | None
    rsi_14: float | None
    macd: float | None
    macd_signal: float | None
    macd_histogram: float | None
    atr_14: float | None
    signals: list[str]
    disclaimer: str = DISCLAIMER


# --- tool functions ---------------------------------------------------------------------

def _day(ts) -> str:
    return ts.strftime("%Y-%m-%d")


def _int(value) -> int | None:
    return int(value) if value is not None and not pd.isna(value) else None


def _pct_change(first, last) -> float | None:
    return _r((last / first - 1) * 100) if first and last is not None else None


def _quote(symbol: str) -> Quote:
    try:
        info = _info(symbol)
    except FinApiError as exc:
        return Quote(symbol=symbol, error=exc.message)
    price = info.get("regularMarketPrice") or info.get("currentPrice")
    prev = info.get("regularMarketPreviousClose") or info.get("previousClose")
    return Quote(
        symbol=symbol, name=info.get("longName") or info.get("shortName"),
        currency=info.get("currency"), market_state=info.get("marketState"), price=_r(price),
        change_pct=_pct_change(prev, price), open=_r(info.get("regularMarketOpen")),
        day_high=_r(info.get("regularMarketDayHigh")), day_low=_r(info.get("regularMarketDayLow")),
        volume=_int(info.get("regularMarketVolume")), previous_close=_r(prev),
    )


def get_quotes(symbols: str | list[str]) -> QuotesResponse:
    symbols = normalize_symbols(symbols)
    with ThreadPoolExecutor(max_workers=min(8, len(symbols))) as pool:
        return QuotesResponse(quotes=list(pool.map(_quote, symbols)))


def get_price_history(symbol: str, start_date: str | None = None, end_date: str | None = None,
                      period: str | None = None, interval: str = "1d",
                      max_points: int = 100) -> HistoryResponse:
    symbol = normalize_symbol(symbol)
    if interval not in INTERVALS:
        raise InvalidInputError(f"interval must be one of {', '.join(INTERVALS)}; got {interval!r}.")
    if not 2 <= max_points <= 1000:
        raise InvalidInputError(f"max_points must be between 2 and 1000; got {max_points}.")
    start, end = resolve_window(start_date, end_date, period, "1mo")
    df = _history(symbol, start, end, interval)
    close = df["Close"].dropna()
    sampled = downsample(df, max_points)
    return HistoryResponse(
        symbol=symbol, interval=interval, start=_day(df.index[0]), end=_day(df.index[-1]),
        points_total=len(df), points_returned=len(sampled),
        summary=HistorySummary(
            first_close=_r(close.iloc[0]), last_close=_r(close.iloc[-1]),
            return_pct=_pct_change(close.iloc[0], close.iloc[-1]),
            high=_r(df["High"].max()), low=_r(df["Low"].min())),
        bars=[Bar(date=_day(ts), open=_r(row.Open), high=_r(row.High), low=_r(row.Low),
                  close=_r(row.Close), volume=_int(row.Volume))
              for ts, row in sampled.iterrows()],
    )


def get_company_profile(symbol: str, include_officers: bool = False,
                        summary_chars: int = 600) -> CompanyProfile:
    symbol = normalize_symbol(symbol)
    if not 0 <= summary_chars <= 5000:
        raise InvalidInputError(f"summary_chars must be between 0 and 5000; got {summary_chars}.")
    info = _info(symbol)
    summary = info.get("longBusinessSummary") or None
    if summary and len(summary) > summary_chars:
        summary = summary[:summary_chars].rsplit(" ", 1)[0] + "…" if summary_chars else None
    officers = None
    if include_officers:
        officers = [Officer(name=o.get("name"), title=o.get("title"))
                    for o in info.get("companyOfficers") or []]
    return CompanyProfile(
        symbol=symbol, name=info.get("longName") or info.get("shortName"),
        quote_type=info.get("quoteType"), sector=info.get("sector"),
        industry=info.get("industry"), country=info.get("country"), website=info.get("website"),
        employees=_int(info.get("fullTimeEmployees")), market_cap=_r(info.get("marketCap"), 0),
        currency=info.get("currency"), summary=summary, officers=officers,
    )


def _signals(last, sma_50, sma_200, rsi_14, macd_line, macd_signal) -> list[str]:
    out = []
    if rsi_14 is not None:
        zone = ("overbought zone (>= 70)" if rsi_14 >= 70 else
                "oversold zone (<= 30)" if rsi_14 <= 30 else "neutral range (30-70)")
        out.append(f"RSI-14 is {rsi_14}: {zone}.")
    if sma_50 is not None and sma_200 is not None:
        side = "above" if sma_50 > sma_200 else "below"
        regime = "golden-cross" if sma_50 > sma_200 else "death-cross"
        out.append(f"SMA-50 ({sma_50}) is {side} SMA-200 ({sma_200}): {regime} regime.")
    if macd_line is not None and macd_signal is not None:
        side = "above" if macd_line > macd_signal else "below"
        tone = "positive" if macd_line > macd_signal else "negative"
        out.append(f"MACD line is {side} its signal line: {tone} momentum.")
    if last is not None and sma_50 is not None:
        out.append(f"Last close {last} is {'above' if last > sma_50 else 'below'} SMA-50.")
    return out


def analyze_stock(symbol: str, start_date: str | None = None, end_date: str | None = None,
                  period: str | None = None) -> Analysis:
    symbol = normalize_symbol(symbol)
    start, end = resolve_window(start_date, end_date, period, "6mo")
    # Fetch extra history before the window so SMA-200 etc. are defined for short windows.
    warm_start = start - timedelta(days=WARMUP_DAYS) if start else None
    df = _history(symbol, warm_start, end, "1d")
    df = df[df["Close"].notna()]
    window = df[df.index.date >= start] if start else df
    if window.empty:
        raise NotFoundError(f"No price data for {symbol} between {start} and {end}. Widen the "
                            "date range (markets are closed on weekends and holidays).")
    close, wclose = df["Close"], window["Close"]
    last = _r(close.iloc[-1])
    sma_50, sma_200, rsi_14 = sma(close, 50), sma(close, 200), rsi(close)
    macd_line, macd_signal, macd_hist = macd(close) or (None, None, None)
    return Analysis(
        symbol=symbol, start=_day(window.index[0]), end=_day(window.index[-1]), last_close=last,
        return_pct=_pct_change(wclose.iloc[0], wclose.iloc[-1]),
        volatility_annualized_pct=annualized_volatility_pct(wclose),
        max_drawdown_pct=max_drawdown_pct(wclose),
        high=_r(window["High"].max()), low=_r(window["Low"].min()),
        sma_50=sma_50, sma_200=sma_200, rsi_14=rsi_14, macd=macd_line, macd_signal=macd_signal,
        macd_histogram=macd_hist, atr_14=atr(df),
        signals=_signals(last, sma_50, sma_200, rsi_14, macd_line, macd_signal),
    )
