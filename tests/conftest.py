import math
from datetime import timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from finapi import core

AAPL_INFO = {
    "quoteType": "EQUITY", "longName": "Apple Inc.", "currency": "USD", "marketState": "REGULAR",
    "regularMarketPrice": 110.0, "regularMarketPreviousClose": 100.0, "regularMarketOpen": 101.0,
    "regularMarketDayHigh": 111.0, "regularMarketDayLow": 99.5, "regularMarketVolume": 123456,
    "sector": "Technology", "industry": "Consumer Electronics", "country": "United States",
    "website": "https://www.apple.com", "fullTimeEmployees": 150000, "marketCap": 3_000_000_000_000,
    "longBusinessSummary": "Apple designs smartphones. " * 100,
    "companyOfficers": [{"name": "Tim Cook", "title": "CEO", "age": 63}],
}


def synthetic_bars(start, end_exclusive):
    """Business-day bars with a gentle uptrend and a deterministic wiggle, tz-aware like yfinance."""
    idx = pd.bdate_range(start, end_exclusive - timedelta(days=1), tz="America/New_York")
    close = pd.Series([100 + 0.3 * i + 3 * math.sin(i / 3) for i in range(len(idx))], index=idx)
    return pd.DataFrame({"Open": close - 0.5, "High": close + 1, "Low": close - 1,
                         "Close": close, "Volume": 1_000_000})


@pytest.fixture
def market(monkeypatch):
    """Replace the yfinance access points with an in-memory fake; records every fetch."""
    m = SimpleNamespace(infos={"AAPL": AAPL_INFO, "MSFT": {**AAPL_INFO, "longName": "Microsoft"}},
                        history_calls=[], info_calls=[], history_df=None, error=None)

    def fake_history(symbol, start, end_exclusive, interval):
        m.history_calls.append((symbol, start, end_exclusive, interval))
        if m.error:
            raise m.error
        if m.history_df is not None:
            return m.history_df
        if symbol not in m.infos:
            return pd.DataFrame()
        return synthetic_bars(start or end_exclusive - timedelta(days=4000), end_exclusive)

    def fake_info(symbol):
        m.info_calls.append(symbol)
        if m.error:
            raise m.error
        return m.infos.get(symbol, {"trailingPegRatio": None})

    monkeypatch.setattr(core, "_fetch_history", fake_history)
    monkeypatch.setattr(core, "_fetch_info", fake_info)
    core._CACHE.clear()
    return m
