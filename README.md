# Financial Data Intelligence API Suite
A modular collection of FastAPI microservices that deliver real-time stock data, historical price series, detailed company fundamentals, and automated analytical insights using Yahoo Finance. Each service operates as an independent, composable unit, enabling flexible integration into dashboards, trading tools, data pipelines, and ML workflows.

## Overview
The suits provides four focused APIs built with FastAPI, Pydantic, and yfinance. Together, they form a lightweight financial data layer capable of powering investor tools, backtesting systems, or educational platforms. Every endpoint includes strict symbol validation, robust exception handling, and standardized JSON responses to ensure predictable and safe consumption.

## Included Microservices
### 1. Real-Time Stock Data API
Retrieves live market metrics including current price, daily high/low, volume, market state, and percentage change from the previous close.
### 2. Historical Stock Data API
Returns structured time-series data—open, high, low, close, and volume—across a user-defined date range, suitable for charting or analytics workflows.
### 3. Company Information API
Provides descriptive metadata such as company name, business summary, sector, industry, and listed officers sourced directly from Yahoo Finance.
### 4. Company Analysis API
Performs higher-level calculations including price deltas, SMA-50/SMA-200 averages, volatility, recent highs/lows, and trend interpretation with narrative investment considerations.

## Architecture
* **FastAPI Service Layer** – separate, self-contained endpoints with clean routing.
* **Pydantic Models** – strict typing and automatic validation for request and response schemas.
* **Data Extraction Engine** – yfinance-based retrieval of market and company data.
* **Analytics Module** – calculations for volatility, returns, moving averages, and qualitative insights.
* **Exception & Validation Framework** – unified response model for errors and invalid inputs.

## Design Principles
* Services operate independently or as a combined suite.
* Consistent JSON schemas across endpoints for seamless client integration.
* Modular structure supporting easy extension into additional financial analyses.
* Deployment-ready design for local or containerized environments.

## Use Cases
* Personal finance dashboards
* ML preprocessing layers for stock-related models
* Alpha research tooling
* Educational or demo apps needing financial data
* Backend support for trading simulations

## Future Enhancements
* Caching layer for reducing redundant Yahoo Finance calls
* Async batching for multi-symbol queries
* Technical-indicator expansion (RSI, MACD, ATR, etc.)
* Optional plug-ins for alternative data sources
