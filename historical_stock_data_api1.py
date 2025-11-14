from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import yfinance as yf
from typing import List, Optional
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
import uvicorn
import pandas as pd

app = FastAPI(
    title="Historical Stock Data API",
    description="API to fetch historical stock market data for a company symbol within a date range using Yahoo Finance",
    version="1.0.0"
)

class HistoricalDataRequest(BaseModel):
    symbol: str
    start_date: str  # Format: YYYY-MM-DD
    end_date: str    # Format: YYYY-MM-DD

class HistoricalDataPoint(BaseModel):
    date: str
    open: Optional[float]
    high: Optional[float]
    low: Optional[float]
    close: Optional[float]
    volume: Optional[int]

class HistoricalDataResponse(BaseModel):
    symbol: str
    data: List[HistoricalDataPoint]

def validate_symbol(symbol: str) -> bool:
    """Validate if the symbol contains only allowed characters"""
    return symbol.isalnum() or ('.' in symbol and all(part.isalnum() for part in symbol.split('.')))

def validate_date(date_str: str) -> bool:
    """Validate date format (YYYY-MM-DD)"""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False

@app.post("/historical_stock", response_model=HistoricalDataResponse)
async def get_historical_stock_data(request: HistoricalDataRequest):
    """
    Retrieve historical stock market data for a given company symbol and date range
    """
    # Validate symbol
    if not request.symbol or not validate_symbol(request.symbol):
        raise HTTPException(status_code=400, detail="Invalid company symbol")

    # Validate dates
    if not validate_date(request.start_date) or not validate_date(request.end_date):
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    try:
        start_date = datetime.strptime(request.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(request.end_date, "%Y-%m-%d")

        # Ensure end_date is not before start_date
        if end_date < start_date:
            raise HTTPException(status_code=400, detail="End date cannot be before start date")

        # Create yfinance Ticker object
        ticker = yf.Ticker(request.symbol)
        # Fetch historical data
        hist_data = ticker.history(start=request.start_date, end=request.end_date)

        if hist_data.empty:
            raise HTTPException(status_code=404, detail=f"No data found for {request.symbol} in the specified date range")

        # Prepare response
        data_points = [
            HistoricalDataPoint(
                date=index.strftime("%Y-%m-%d"),
                open=round(row["Open"], 2) if not pd.isna(row["Open"]) else None,
                high=round(row["High"], 2) if not pd.isna(row["High"]) else None,
                low=round(row["Low"], 2) if not pd.isna(row["Low"]) else None,
                close=round(row["Close"], 2) if not pd.isna(row["Close"]) else None,
                volume=int(row["Volume"]) if not pd.isna(row["Volume"]) else None
            )
            for index, row in hist_data.iterrows()
        ]

        response = HistoricalDataResponse(
            symbol=request.symbol.upper(),
            data=data_points
        )

        return response

    except Exception as e:
        if "404" in str(e):
            raise HTTPException(status_code=404, detail=f"Company symbol {request.symbol} not found")
        raise HTTPException(status_code=500, detail=f"Error retrieving historical data: {str(e)}")

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail}
    )

if __name__ == "__main__":
    # Use default symbol and date range (last 30 days) for sample payload
    default_symbol = "AAPL"
    default_end_date = datetime.now().strftime("%Y-%m-%d")
    default_start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    sample_payload = {
        "symbol": default_symbol,
        "start_date": default_start_date,
        "end_date": default_end_date
    }
    endpoint_url = "http://localhost:8000/historical_stock"
    print(f"POST Endpoint: {endpoint_url}")
    print(f"Sample Payload: {sample_payload}")
    print("Use a POST client (e.g., curl, Postman, or http://localhost:8000/docs) to send the request")
    print(f"Example curl: curl -X POST {endpoint_url} -H 'Content-Type: application/json' -d '{{\"symbol\": \"{default_symbol}\", \"start_date\": \"{default_start_date}\", \"end_date\": \"{default_end_date}\"}}'")
    uvicorn.run("historical_stock_data_api1:app", host="0.0.0.0", port=8000, reload=False)