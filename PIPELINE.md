# Trading Pipeline Data Flow

## Overview

The contracts directory modules now work together in a coordinated pipeline, where data flows from one module to the next:

```
market_data.py → signals.py → portfolio.py → risk.py → execution.py → orders.py
```

## Pipeline Stages

### Stage 1: Market Data Ingestion (`market_data.py`)
**Input:** Ticker symbol(s) and date range  
**Output:** DataFrame with columns: `ticker`, `date`, `open`, `high`, `low`, `close`, `volume`

```python
market_data = get_market_data(
    tickers=['AAPL', 'MSFT', 'GOOGL', ...],
    start_date='2024-01-01',
    end_date='2024-08-31'
)
# Returns: DataFrame with OHLCV data for all tickers
```

### Stage 2: Signal Generation (`signals.py`)
**Input:** Market data DataFrame from Stage 1  
**Output:** Lists of bullish/bearish tickers + signals DataFrame

```python
bullish_tickers, bearish_tickers, signals_df = signal_generator(market_data)
# Returns:
#   - bullish_tickers: ['AAPL', 'MSFT', ...]  (tickers with bullish signals)
#   - bearish_tickers: ['GOOGL', ...]         (tickers with bearish signals)
#   - signals_df: DataFrame with calculated indicators (RSI, MACD, EMA)
```

**Signal Logic:**
- Calculates RSI (Relative Strength Index) - fast and slow periods
- Calculates MACD (Moving Average Convergence Divergence)
- Calculates EMA (Exponential Moving Average)
- Bullish signal when:
  - EMA(5) > EMA(15) (short-term trend up)
  - FAST_RSI > SLOW_RSI (momentum positive)
  - MACD > Signal Line (convergence positive)
  - Volume increasing
  - Price advancing

### Stage 3: Portfolio Performance Analysis (`portfolio.py`)
**Input:** Bullish tickers from Stage 2  
**Output:** Top performing tickers (list)

```python
top_performers = get_top_performers(
    bullish_tickers=bullish_tickers,
    keep=20,
    lookback_days=30
)
# Returns: ['AAPL', 'MSFT', ...]  (top 20 by return)
```

**Calculation:**
- Fetches market data for each bullish ticker
- Calculates returns: `(latest_close - first_close) / first_close`
- Ranks by return (highest first)
- Returns top N performers

### Stage 4: Portfolio Optimization (`risk.py`)
**Input:** Top performer tickers from Stage 3  
**Output:** DataFrame with portfolio weights

```python
weights_df = port_opt(
    tickers=top_performers,
    lookback_days=30
)
# Returns: DataFrame with columns ['ticker', 'weights']
# Example:
#   ticker    weights
#   AAPL      0.25
#   MSFT      0.20
#   GOOGL     0.15
#   ...
```

**Optimization:**
- Fetches market data for selected tickers
- Calculates daily returns
- Uses Riskfolio library with:
  - Mean-variance optimization
  - Sharpe ratio as objective
  - Filters out weights < 1% and normalizes
  - Returns sorted by weight (descending)

### Stage 5: Trade Execution (`execution.py` + `orders.py`)
**Input:** 
- Connected IB instance
- Target weights DataFrame from Stage 4
- Current account value

**Output:** List of Trade objects

```python
trades = execute_rebalance(
    ib=ib_connection,
    target_weights=weights_df,
    account_value=account_value,
    sell_timeout=300.0
)
# Returns: List of Trade handles from ib_insync

# Execution flow:
# 1. Calculates current holdings vs target weights
# 2. Submits ALL SELL orders for positions to be reduced/closed
# 3. WAITS for all sell orders to fill (or timeout)
# 4. Only THEN submits BUY orders for new positions
# 5. Returns all submitted trades for monitoring
```

**Order Behavior:**
- Market orders for quick execution
- GTC (Good-Till-Cancelled) time in force
- Outside regular hours enabled
- Sell-before-buy sequencing (critical for paper trading)

## End-to-End Example

```python
from src.contracts.pipeline import run_analysis_pipeline, run_trading_pipeline
from ib_insync import IB

# Option 1: Just run analysis (no execution)
results = run_analysis_pipeline(
    tickers=['AAPL', 'MSFT', 'GOOGL', ...],
    lookback_days=30,
    num_signals=20
)

# Results structure:
# {
#     'status': 'success',
#     'bullish_tickers': [...],      # From signals
#     'bearish_tickers': [...],      # From signals
#     'top_performers': [...],       # From portfolio
#     'weights': DataFrame,          # From risk
#     'market_data': DataFrame,      # Raw market data
#     'signals_data': DataFrame      # Signals with indicators
# }

# Option 2: Run analysis + execute trades
ib = IB()
ib.connect('127.0.0.1', 7497)  # Connect to IB Gateway

results = run_trading_pipeline(
    ib=ib,
    tickers=['AAPL', 'MSFT', 'GOOGL', ...],
    lookback_days=30,
    num_signals=20,
    account_value=None,      # Auto-fetched from account
    sell_timeout=300.0       # 5 minute timeout for fills
)

# Results include:
# {
#     ...(all analysis results)...
#     'trades': [Trade1, Trade2, ...],
#     'execution_status': 'success'
# }
```

## Data Flow Summary

| Stage | Input | Output | Key Function |
|-------|-------|--------|--------------|
| 1 | Tickers + dates | OHLCV DataFrame | `get_market_data()` |
| 2 | Market data | Bullish tickers list | `signal_generator()` |
| 3 | Bullish tickers | Top 20 tickers | `get_top_performers()` |
| 4 | Top tickers | Weights DataFrame | `port_opt()` |
| 5 | Weights + IB connection | Trade objects | `execute_rebalance()` |

## Key Design Decisions

1. **Pure Functions**: Each module function accepts all needed inputs as parameters
2. **Explicit Data Flow**: No global state; data is passed between stages
3. **Error Handling**: Each stage includes try-except with fallback values
4. **Sell-Before-Buy**: Execution waits for all sells to fill before buying
5. **Flexibility**: Analysis can run independently of execution
6. **Logging**: Pipeline prints status at each stage

## Testing the Pipeline

```python
# Test with mock data (no API calls needed)
import pandas as pd
from src.contracts.signals import signal_generator

mock_data = pd.DataFrame({
    'ticker': ['AAPL'] * 20,
    'date': pd.date_range('2024-01-01', periods=20),
    'close': [100 + i*2 for i in range(20)],
    'volume': [1000000] * 20
})

bullish, bearish, signals = signal_generator(mock_data)
print(f"Bullish: {bullish}, Bearish: {bearish}")
```
