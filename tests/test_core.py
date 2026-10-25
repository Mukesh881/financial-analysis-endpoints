from datetime import date, timedelta

import pytest

from finapi import core
from finapi.core import InvalidInputError


@pytest.mark.parametrize(
    "raw, expected",
    [("brk-b", "BRK-B"), ("^GSPC", "^GSPC"), ("EURUSD=X", "EURUSD=X"),
     ("BTC-USD", "BTC-USD"), (" reliance.ns ", "RELIANCE.NS"), ("aapl", "AAPL")],
)
def test_normalize_symbol_accepts_real_tickers(raw, expected):
    assert core.normalize_symbol(raw) == expected


@pytest.mark.parametrize("raw", ["", "AA PL", "A;DROP", "A" * 16, "-AAPL"])
def test_normalize_symbol_rejects(raw):
    with pytest.raises(InvalidInputError):
        core.normalize_symbol(raw)


def test_normalize_symbols_dedupes():
    assert core.normalize_symbols("aapl, AAPL ,msft") == ["AAPL", "MSFT"]
    assert core.normalize_symbols(["msft", "aapl"]) == ["MSFT", "AAPL"]
    with pytest.raises(InvalidInputError):
        core.normalize_symbols([f"S{i}" for i in range(11)])
    with pytest.raises(InvalidInputError):
        core.normalize_symbols("")


def test_resolve_window_explicit_dates():
    assert core.resolve_window("2024-01-02", "2024-03-01", None, "1mo") == (
        date(2024, 1, 2), date(2024, 3, 1))


@pytest.mark.parametrize(
    "start, end, period",
    [("2024-03-01", "2024-01-01", None), ("2024/01/01", "2024-02-01", None),
     ("2024-01-01", "2024-02-01", "1mo"), (None, None, "3w"), (None, "2024-02-01", None)],
)
def test_resolve_window_rejects(start, end, period):
    with pytest.raises(InvalidInputError):
        core.resolve_window(start, end, period, "1mo")


def test_resolve_window_start_only_runs_to_today():
    assert core.resolve_window("2024-01-01", None, None, "1mo") == (date(2024, 1, 1), date.today())


def test_resolve_window_clamps_future_end():
    future = (date.today() + timedelta(days=30)).isoformat()
    assert core.resolve_window("2024-01-01", future, None, "1mo")[1] == date.today()


def test_resolve_window_periods():
    today = date.today()
    assert core.resolve_window(None, None, None, "1mo") == (today - timedelta(days=31), today)
    assert core.resolve_window(None, None, "ytd", "1mo") == (date(today.year, 1, 1), today)
    assert core.resolve_window(None, None, "max", "1mo") == (None, today)


# --- indicators -------------------------------------------------------------------------

import pandas as pd  # noqa: E402


def _bars(closes, spread=2.0):
    c = pd.Series(closes, dtype=float)
    return pd.DataFrame({"Open": c, "High": c + spread / 2, "Low": c - spread / 2, "Close": c,
                         "Volume": 1000})


def test_sma():
    close = pd.Series(range(1, 11), dtype=float)
    assert core.sma(close, 5) == 8.0
    assert core.sma(close, 11) is None


def test_rsi_extremes():
    assert core.rsi(pd.Series(range(1, 40), dtype=float)) == 100.0
    assert core.rsi(pd.Series(range(40, 1, -1), dtype=float)) == 0.0
    assert core.rsi(pd.Series([1.0] * 5)) is None


def test_macd_constant_series_is_zero():
    assert core.macd(pd.Series([10.0] * 40)) == (0.0, 0.0, 0.0)
    assert core.macd(pd.Series([10.0] * 34)) is None


def test_atr_flat_bars():
    assert core.atr(_bars([50.0] * 30)) == 2.0
    assert core.atr(_bars([50.0] * 5)) is None


def test_volatility_and_drawdown():
    assert core.annualized_volatility_pct(pd.Series([10.0] * 30)) == 0.0
    assert core.max_drawdown_pct(pd.Series([100.0, 120.0, 60.0, 90.0])) == -50.0
    assert core.max_drawdown_pct(pd.Series([1.0, 2.0, 3.0])) == 0.0


def test_downsample_keeps_first_and_last():
    df = _bars(range(10))
    two = core.downsample(df, 2)
    assert list(two["Close"]) == [0.0, 9.0]
    assert len(core.downsample(df, 50)) == 10
    assert len(core.downsample(df, 4)) == 4
