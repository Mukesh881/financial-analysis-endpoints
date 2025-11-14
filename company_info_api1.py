from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import yfinance as yf
from typing import List, Dict, Optional
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(
    title="Company Information API",
    description="API to retrieve detailed company information using Yahoo Finance",
    version="1.0.0"
)

class CompanySymbol(BaseModel):
    symbol: str

class Officer(BaseModel):
    name: Optional[str]
    title: Optional[str]

class CompanyInfoResponse(BaseModel):
    symbol: str
    company_name: Optional[str]
    business_summary: Optional[str]
    industry: Optional[str]
    sector: Optional[str]
    officers: Optional[List[Officer]]

def validate_symbol(symbol: str) -> bool:
    """Validate if the symbol contains only allowed characters"""
    return symbol.isalnum() or ('.' in symbol and all(part.isalnum() for part in symbol.split('.')))

@app.get("/company/{symbol}", response_model=CompanyInfoResponse)
async def get_company_info(symbol: str):
    """
    Retrieve detailed company information for a given stock symbol
    """
    if not symbol or not validate_symbol(symbol):
        raise HTTPException(status_code=400, detail="Invalid company symbol")

    try:
        # Create yfinance Ticker object
        ticker = yf.Ticker(symbol)
        info = ticker.info

        # Extract officer information
        officers = []
        try:
            for officer in ticker.info.get('companyOfficers', []):
                officers.append(Officer(
                    name=officer.get('name'),
                    title=officer.get('title')
                ))
        except (KeyError, TypeError):
            officers = []

        # Prepare response
        response = CompanyInfoResponse(
            symbol=symbol.upper(),
            company_name=info.get('longName'),
            business_summary=info.get('longBusinessSummary'),
            industry=info.get('industry'),
            sector=info.get('sector'),
            officers=officers
        )

        return response

    except Exception as e:
        if "404" in str(e):
            raise HTTPException(status_code=404, detail=f"Company symbol {symbol} not found")
        raise HTTPException(status_code=500, detail=f"Error retrieving company data: {str(e)}")

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
    endpoint_url = f"http://localhost:8000/company/{company_symbol.upper()}"
    print(f"API Endpoint URL (click to open): {endpoint_url}")
    uvicorn.run("company_info_api1:app", host="localhost", port=8000, reload=False)