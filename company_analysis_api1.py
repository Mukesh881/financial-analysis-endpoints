from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import yfinance as yf
from typing import List, Optional
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
import uvicorn
import pandas as pd
import numpy as np

app = FastAPI(
    title="Company Analysis API",
    description="API to perform comprehensive analysis of a company based on historical stock data and provide actionable insights",
    version="1.0.0"
)

class AnalysisRequest(BaseModel):
    symbol: str
    start_date: str  # Format: YYYY-MM-DD
    end_date: str    # Format: YYYY-MM-DD

class AnalysisMetrics(BaseModel):
    price_change_absolute: Optional[float]
    price_change_percent: Optional[float]
    volatility: Optional[float]
    sma_50: Optional[float]
    sma_200: Optional[float]
    recent_high: Optional[float]
    recent_low: Optional[float]

class Insight(BaseModel):
    trend_direction: str
    volatility_assessment: str
    investment_considerations: str

class AnalysisResponse(BaseModel):
    symbol: str
    metrics: AnalysisMetrics
    insights: Insight

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

@app.post("/company_analysis", response_model=AnalysisResponse)
async def get_company_analysis(request: AnalysisRequest):
    """
    Perform comprehensive analysis of a company based on historical stock data and provide actionable insights
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

        # Calculate metrics
        close_prices = hist_data["Close"]
        first_price = close_prices.iloc[0]
        last_price = close_prices.iloc[-1]
        price_change_absolute = round(last_price - first_price, 2) if not pd.isna(first_price) and not pd.isna(last_price) else None
        price_change_percent = round(((last_price - first_price) / first_price) * 100, 2) if price_change_absolute is not None and first_price != 0 else None

        # Volatility (standard deviation of daily returns)
        daily_returns = close_prices.pct_change().dropna()
        volatility = round(np.std(daily_returns) * np.sqrt(252) * 100, 2) if not daily_returns.empty else None  # Annualized volatility

        # Moving averages
        sma_50 = round(close_prices.rolling(window=50).mean().iloc[-1], 2) if len(close_prices) >= 50 else None
        sma_200 = round(close_prices.rolling(window=200).mean().iloc[-1], 2) if len(close_prices) >= 200 else None

        # Recent high and low
        recent_high = round(close_prices.max(), 2) if not close_prices.empty else None
        recent_low = round(close_prices.min(), 2) if not close_prices.empty else None

        # Generate insights
        trend_direction = "Neutral"
        if price_change_percent is not None:
            if price_change_percent > 5:
                trend_direction = "Bullish"
            elif price_change_percent < -5:
                trend_direction = "Bearish"

        if sma_50 is not None and sma_200 is not None:
            if sma_50 > sma_200:
                trend_direction = "Bullish (SMA crossover)" if trend_direction != "Bullish" else trend_direction
            elif sma_50 < sma_200:
                trend_direction = "Bearish (SMA crossover)" if trend_direction != "Bearish" else trend_direction

        volatility_assessment = "Moderate"
        if volatility is not None:
            if volatility > 30:
                volatility_assessment = "High"
            elif volatility < 15:
                volatility_assessment = "Low"

        investment_considerations = (
            f"The stock exhibits a {trend_direction.lower()} trend with {volatility_assessment.lower()} volatility. "
            f"Consider monitoring for {'entry' if 'Bullish' in trend_direction else 'exit'} points near recent {'highs' if 'Bullish' in trend_direction else 'lows'} "
            f"({recent_high if recent_high else 'N/A'} or {recent_low if recent_low else 'N/A'}). "
            f"{'Long-term investors may find this stable' if volatility_assessment == 'Low' else 'Short-term traders may capitalize on price swings' if volatility_assessment == 'High' else 'Balance risk with potential returns'}. "
            "Always consult a financial advisor."
        )

        # Prepare response
        response = AnalysisResponse(
            symbol=request.symbol.upper(),
            metrics=AnalysisMetrics(
                price_change_absolute=price_change_absolute,
                price_change_percent=price_change_percent,
                volatility=volatility,
                sma_50=sma_50,
                sma_200=sma_200,
                recent_high=recent_high,
                recent_low=recent_low
            ),
            insights=Insight(
                trend_direction=trend_direction,
                volatility_assessment=volatility_assessment,
                investment_considerations=investment_considerations
            )
        )

        return response

    except Exception as e:
        if "404" in str(e):
            raise HTTPException(status_code=404, detail=f"Company symbol {request.symbol} not found")
        raise HTTPException(status_code=500, detail=f"Error performing analysis: {str(e)}")

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail}
    )

if __name__ == "__main__":
    # Use default symbol and date range (last 90 days) for sample payload
    default_symbol = input("Enter company symbol (e.g., AAPL, MSFT): ").strip()
    if not default_symbol:
        default_symbol = "AAPL"  # Default to AAPL if no input provided
    default_end_date = datetime.now().strftime("%Y-%m-%d")
    default_start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    sample_payload = {
        "symbol": default_symbol,
        "start_date": default_start_date,
        "end_date": default_end_date
    }
    endpoint_url = "http://localhost:8000/company_analysis"
    print(f"POST Endpoint: {endpoint_url}")
    print(f"Sample Payload: {sample_payload}")
    print("Use a POST client (e.g., curl, Postman, or http://localhost:8000/docs) to send the request")
    print(f"Example curl: curl -X POST {endpoint_url} -H 'Content-Type: application/json' -d '{{\"symbol\": \"{default_symbol}\", \"start_date\": \"{default_start_date}\", \"end_date\": \"{default_end_date}\"}}'")
    uvicorn.run("company_analysis_api1:app", host="0.0.0.0", port=8000, reload=False)