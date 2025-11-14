from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import yfinance as yf
from typing import Optional
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(
    title="Real-Time Stock Data API",
    description="API to fetch real-time stock market data using Yahoo Finance",
    version="1.0.0"
)

class StockDataResponse(BaseModel):
    symbol: str
    market_state: Optional[str]
    current_price: Optional[float]
    percentage_change: Optional[float]
    open_price: Optional[float]
    high_price: Optional[float]
    low_price: Optional[float]
    volume: Optional[int]
    previous_close: Optional[float]

def validate_symbol(symbol: str) -> bool:
    """Validate if the symbol contains only allowed characters"""
    return symbol.isalnum() or ('.' in symbol and all(part.isalnum() for part in symbol.split('.')))

@app.get("/stock/{symbol}", response_model=StockDataResponse)
async def get_stock_data(symbol: str):
    """
    Retrieve real-time stock market data for a given company symbol
    """
    if not symbol or not validate_symbol(symbol):
        raise HTTPException(status_code=400, detail="Invalid company symbol")

    try:
        # Create yfinance Ticker object
        ticker = yf.Ticker(symbol)
        info = ticker.info

        # Calculate percentage change
        current_price = info.get('regularMarketPrice')
        previous_close = info.get('regularMarketPreviousClose')
        percentage_change = None
        if current_price is not None and previous_close is not None and previous_close != 0:
            percentage_change = ((current_price - previous_close) / previous_close) * 100

        # Prepare response
        response = StockDataResponse(
            symbol=symbol.upper(),
            market_state=info.get('marketState'),
            current_price=current_price,
            percentage_change=round(percentage_change, 2) if percentage_change is not None else None,
            open_price=info.get('regularMarketOpen'),
            high_price=info.get('regularMarketDayHigh'),
            low_price=info.get('regularMarketDayLow'),
            volume=info.get('regularMarketVolume'),
            previous_close=previous_close
        )

        return response

    except Exception as e:
        if "404" in str(e):
            raise HTTPException(status_code=404, detail=f"Company symbol {symbol} not found")
        raise HTTPException(status_code=500, detail=f"Error retrieving stock data: {str(e)}")

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail}
    )

if __name__ == "__main__":
    # Prompt for company symbol
    company_symbol = input("Enter company symbol (e.g., AAPL, MSFT): ").strip()
    if not company_symbol:
        company_symbol = "AAPL"  # Default to AAPL if no input provided
    endpoint_url = f"http://localhost:8000/stock/{company_symbol.upper()}"
    print(f"API Endpoint URL (click to open): {endpoint_url}")
    uvicorn.run("stock_data_api1:app", host="0.0.0.0", port=8000, reload=False)