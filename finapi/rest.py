"""REST front door. Handlers are plain `def` so blocking yfinance calls run in FastAPI's threadpool."""

import os

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from finapi import core

STATUS = {"invalid_input": 400, "not_found": 404, "upstream_error": 502}

app = FastAPI(
    title="Financial Data Tools API",
    description="Quotes, price history, company profiles and technical analysis from Yahoo "
                "Finance, shaped for LLM agents. The same tools are available over MCP.",
    version="2.0.0",
)


def _error(status: int, type_: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"type": type_, "message": message}})


@app.exception_handler(core.FinApiError)
def _finapi_error(request: Request, exc: core.FinApiError):
    return _error(STATUS.get(exc.type, 500), exc.type, exc.message)


@app.exception_handler(RequestValidationError)
def _validation_error(request: Request, exc: RequestValidationError):
    msg = "; ".join(f"{'.'.join(map(str, e['loc'][1:]))}: {e['msg']}" for e in exc.errors())
    return _error(400, "invalid_input", msg)


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}


@app.get("/v1/quotes", operation_id="get_quotes", response_model=core.QuotesResponse)
def quotes(symbols: str = Query(..., description="Comma-separated tickers, max 10. "
                                                 "E.g. AAPL,MSFT,^GSPC")):
    """Latest price snapshot for one or more symbols. Unknown symbols get a per-item error."""
    return core.get_quotes(symbols)


@app.get("/v1/history/{symbol}", operation_id="get_price_history",
         response_model=core.HistoryResponse)
def history(symbol: str, start_date: str | None = None, end_date: str | None = None,
            period: str | None = Query(None, description=f"One of {', '.join(core.PERIODS)}"),
            interval: str = Query("1d", description="1d, 1wk or 1mo"),
            max_points: int = Query(100, ge=2, le=1000)):
    """OHLCV bars (downsampled to max_points) plus a range summary. Default window: 1mo."""
    return core.get_price_history(symbol, start_date, end_date, period, interval, max_points)


@app.get("/v1/company/{symbol}", operation_id="get_company_profile",
         response_model=core.CompanyProfile)
def company(symbol: str, include_officers: bool = False,
            summary_chars: int = Query(600, ge=0, le=5000)):
    """Company or fund profile: sector, industry, size and a truncated business summary."""
    return core.get_company_profile(symbol, include_officers, summary_chars)


@app.get("/v1/analysis/{symbol}", operation_id="analyze_stock", response_model=core.Analysis)
def analysis(symbol: str, start_date: str | None = None, end_date: str | None = None,
             period: str | None = Query(None, description=f"One of {', '.join(core.PERIODS)}")):
    """Return, volatility, drawdown, SMA-50/200, RSI-14, MACD, ATR-14 and signals. Default 6mo."""
    return core.analyze_stock(symbol, start_date, end_date, period)


def main():
    import uvicorn

    uvicorn.run(app, host=os.getenv("FINAPI_HOST", "127.0.0.1"),
                port=int(os.getenv("FINAPI_PORT", "8000")))
