"""
Data pipeline orchestrator for the trading system.

Pipeline flow:
1. market_data → gather OHLCV data for multiple tickers
2. signals → identify bullish/bearish tickers
3. portfolio → calculate returns for bullish tickers, select top performers
4. risk → optimize portfolio weights using the top performers
5. execution → execute trades using the calculated weights
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

from ib_insync import IB

from .market_data import get_market_data
from .signals import signal_generator
from .portfolio import get_top_performers
from .risk import port_opt
from .execution import execute_rebalance


def run_analysis_pipeline(
    tickers: list,
    lookback_days: int = 30,
    num_signals: int = 20,
    signal_threshold_days: int = 5,
) -> dict:
    """
    Run the complete analysis pipeline without execution.
    
    Args:
        tickers (list): List of ticker symbols to analyze
        lookback_days (int): Number of days to look back for analysis
        num_signals (int): Number of top performers to select
        signal_threshold_days (int): Minimum days of data required for signals
    
    Returns:
        dict: Results containing bullish tickers, bearish tickers, and calculated weights
    """
    print(f"Starting analysis pipeline for {len(tickers)} tickers...")
    
    # Step 1: Gather market data
    print("Step 1: Gathering market data...")
    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
    market_data = get_market_data(tickers, start_date=start_date)
    
    if market_data.empty:
        print("Error: No market data retrieved")
        return {
            'status': 'failed',
            'error': 'No market data retrieved'
        }
    
    print(f"  Retrieved data for {market_data['ticker'].nunique()} tickers")
    
    # Step 2: Generate signals
    print("Step 2: Generating trading signals...")
    bullish_tickers, bearish_tickers, signals_df = signal_generator(market_data)
    print(f"  Bullish tickers: {len(bullish_tickers)}")
    print(f"  Bearish tickers: {len(bearish_tickers)}")
    
    if not bullish_tickers:
        print("Warning: No bullish signals found")
        return {
            'status': 'partial',
            'bullish_tickers': [],
            'bearish_tickers': bearish_tickers,
            'weights': pd.DataFrame(columns=['ticker', 'weights'])
        }
    
    # Step 3: Calculate returns for bullish tickers
    print("Step 3: Calculating returns for bullish tickers...")
    top_performers = get_top_performers(bullish_tickers, keep=num_signals, lookback_days=lookback_days)
    print(f"  Top {len(top_performers)} performers selected")
    
    if not top_performers:
        print("Warning: No top performers identified")
        return {
            'status': 'partial',
            'bullish_tickers': bullish_tickers,
            'bearish_tickers': bearish_tickers,
            'weights': pd.DataFrame(columns=['ticker', 'weights'])
        }
    
    # Step 4: Calculate portfolio weights
    print("Step 4: Calculating portfolio weights...")
    weights_df = port_opt(top_performers, lookback_days=lookback_days)
    print(f"  Calculated weights for {len(weights_df)} tickers")
    
    return {
        'status': 'success',
        'bullish_tickers': bullish_tickers,
        'bearish_tickers': bearish_tickers,
        'top_performers': top_performers,
        'market_data': market_data,
        'signals_data': signals_df,
        'weights': weights_df
    }


def run_trading_pipeline(
    ib: IB,
    tickers: list,
    lookback_days: int = 30,
    num_signals: int = 20,
    account_value: Optional[float] = None,
    sell_timeout: float = 300.0,
) -> dict:
    """
    Run the complete pipeline including trade execution.
    
    Args:
        ib (IB): Connected ib_insync IB instance
        tickers (list): List of ticker symbols to analyze
        lookback_days (int): Number of days to look back for analysis
        num_signals (int): Number of top performers to select
        account_value (float): Account net liquidation value (auto-fetched if None)
        sell_timeout (float): Timeout for waiting on sell orders (seconds)
    
    Returns:
        dict: Results including analysis and trade execution status
    """
    # Run analysis pipeline
    analysis_results = run_analysis_pipeline(
        tickers=tickers,
        lookback_days=lookback_days,
        num_signals=num_signals
    )
    
    if analysis_results['status'] != 'success':
        print("Analysis pipeline did not produce complete results")
        return analysis_results
    
    # Step 5: Execute trades
    print("Step 5: Executing trades...")
    try:
        trades = execute_rebalance(
            ib=ib,
            target_weights=analysis_results['weights'],
            account_value=account_value,
            sell_timeout=sell_timeout
        )
        print(f"  Submitted {len(trades)} trades")
        
        return {
            **analysis_results,
            'trades': trades,
            'execution_status': 'success'
        }
    except Exception as e:
        print(f"Error during trade execution: {e}")
        return {
            **analysis_results,
            'execution_status': 'failed',
            'execution_error': str(e)
        }
