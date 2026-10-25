"""Shared core: errors, validation, market data access, indicators and the tool functions.

REST (`finapi.rest`) and MCP (`finapi.mcp_server`) are thin wrappers over this module.
"""

import re
from datetime import date, datetime, timedelta


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
