from datetime import date, timedelta

import pandas as pd
import pytest

from finapi import core
from finapi.core import InvalidInputError, NotFoundError, UpstreamError
from tests.conftest import synthetic_bars


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


# --- service functions ------------------------------------------------------------------



def test_history_end_date_inclusive(market):
    res = core.get_price_history("aapl", start_date="2024-01-02", end_date="2024-01-31")
    assert market.history_calls[0][2] == date(2024, 2, 1)
    assert res.bars[-1].date == "2024-01-31"
    assert res.symbol == "AAPL"


def test_history_downsamples_and_summarises(market):
    res = core.get_price_history("AAPL", start_date="2023-01-02", end_date="2023-12-29",
                                 max_points=10)
    assert res.points_returned == len(res.bars) == 10
    assert res.points_total > 200
    assert res.bars[0].date == "2023-01-02" and res.bars[-1].date == "2023-12-29"
    s = res.summary
    assert s.return_pct == round((s.last_close / s.first_close - 1) * 100, 2)
    assert s.high >= s.last_close and s.low <= s.first_close


def test_history_nan_row_becomes_none(market):
    df = synthetic_bars(date(2024, 1, 2), date(2024, 1, 10))
    df.iloc[2, df.columns.get_loc("Close")] = float("nan")
    df.iloc[2, df.columns.get_loc("Volume")] = float("nan")
    market.history_df = df
    res = core.get_price_history("AAPL", start_date="2024-01-02", end_date="2024-01-09")
    assert res.bars[2].close is None and res.bars[2].volume is None
    res.model_dump_json()  # must serialise (no NaN)


def test_history_empty_is_not_found(market):
    market.history_df = pd.DataFrame()
    with pytest.raises(NotFoundError, match="widen"):
        core.get_price_history("AAPL", start_date="2024-01-06", end_date="2024-01-07")


def test_history_rejects_bad_interval_and_points(market):
    with pytest.raises(InvalidInputError):
        core.get_price_history("AAPL", interval="1h")
    with pytest.raises(InvalidInputError):
        core.get_price_history("AAPL", max_points=1)


def test_analysis_has_sma_200_for_short_window(market):
    res = core.analyze_stock("AAPL", start_date="2024-01-02", end_date="2024-04-01")
    assert market.history_calls[0][1] == date(2024, 1, 2) - timedelta(days=300)
    assert res.sma_200 is not None and res.sma_50 is not None
    assert res.start == "2024-01-02" and res.end == "2024-04-01"
    full = synthetic_bars(date(2024, 1, 2) - timedelta(days=300), date(2024, 4, 2))["Close"]
    window = full[full.index.date >= date(2024, 1, 2)]
    assert res.return_pct == round((window.iloc[-1] / window.iloc[0] - 1) * 100, 2)


def test_analysis_signals_and_disclaimer(market):
    res = core.analyze_stock("AAPL")
    assert res.rsi_14 is not None and res.macd is not None and res.atr_14 is not None
    assert any("SMA-50" in s and "SMA-200" in s for s in res.signals)
    assert any(s.startswith("RSI-14") for s in res.signals)
    assert res.disclaimer == "Informational metrics only, not investment advice."
    assert res.volatility_annualized_pct > 0 and res.max_drawdown_pct <= 0


def test_quotes_per_symbol_error(market):
    res = core.get_quotes("AAPL,NOPE")
    aapl, nope = res.quotes
    assert aapl.price == 110.0 and aapl.change_pct == 10.0 and aapl.error is None
    assert nope.symbol == "NOPE" and nope.price is None and "NOPE" in nope.error


def test_profile_truncates_summary_and_hides_officers(market):
    res = core.get_company_profile("AAPL")
    assert res.name == "Apple Inc." and res.officers is None
    assert len(res.summary) <= 601 and res.summary.endswith("…")
    full = core.get_company_profile("AAPL", include_officers=True, summary_chars=5000)
    assert full.officers[0].name == "Tim Cook"
    assert not full.summary.endswith("…")


def test_unknown_info_is_not_found(market):
    with pytest.raises(NotFoundError, match="NOPE"):
        core.get_company_profile("NOPE")


def test_provider_exception_becomes_upstream(market):
    market.error = ConnectionError("tunnel failed")
    with pytest.raises(UpstreamError, match="tunnel failed"):
        core.get_price_history("AAPL")
    with pytest.raises(UpstreamError):
        core.get_company_profile("AAPL")


def test_info_cached(market):
    core.get_company_profile("AAPL")
    core.get_quotes(["AAPL"])
    assert market.info_calls == ["AAPL"]


def test_cache_is_bounded(market, monkeypatch):
    monkeypatch.setattr(core, "MAX_CACHE_ENTRIES", 5)
    for day in range(1, 20):
        core.get_price_history("AAPL", start_date=f"2024-01-{day:02d}", end_date="2024-02-01")
    assert len(core._CACHE) <= 5
