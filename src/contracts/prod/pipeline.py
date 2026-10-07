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
from typing import Optional

from ib_insync import IB

from .market_data import get_market_data
from ..signals import signal_generator
from .portfolio import get_top_monthly_performers
from .risk import port_opt
from ..execution import execute_rebalance
from ..rebalance import RebalanceProposal


def run_analysis_pipeline(
    tickers: list,
    lookback_months: int = 3,
    num_signals: int = 20,
    signal_threshold_days: int = 5,
    lookback_days: int | None = None,
) -> dict:
    """
    Run the complete analysis pipeline without execution.
    
    Args:
        tickers (list): List of ticker symbols to analyze
        lookback_months (int): Number of months to look back for analysis
        num_signals (int): Number of top performers to select
        signal_threshold_days (int): Minimum days of data required for signals
    
    Returns:
        dict: Results containing bullish tickers, bearish tickers, and calculated weights
    """
    if lookback_days is not None:
        lookback_months = max(1, round(lookback_days / 30))
    lookback_months = max(1, int(lookback_months))
    print(f"Starting analysis pipeline for {len(tickers)} tickers...")
    
    # Step 1: Gather market data
    print("Step 1: Gathering market data...")
    market_data = get_market_data(tickers, period='5y', interval='1mo')
    
    if market_data.empty:
        print("Error: No market data retrieved")
        return {
            'status': 'failed',
            'error': 'No market data retrieved'
        }
    
    print(f"Retrieved data for {market_data['ticker'].nunique()} tickers")
    
    # Step 2: Generate signals
    print("Step 2: Generating trading signals...")
    signal_dates = pd.to_datetime(market_data['date'], errors='coerce')
    completed_market_data = market_data[
        signal_dates.dt.to_period('M') < pd.Timestamp.now().to_period('M')
    ]
    if completed_market_data.empty:
        completed_market_data = market_data
    raw_bullish_tickers, bearish_tickers, signals_df = signal_generator(completed_market_data)
    print(f"  Bullish tickers: {len(raw_bullish_tickers)}")
    print(f"  Bearish tickers: {len(bearish_tickers)}")
    
    if not raw_bullish_tickers:
        print("Warning: No bullish signals found")
        return {
            'status': 'partial',
            'bullish_tickers': [],
            'bearish_tickers': bearish_tickers,
            'weights': pd.DataFrame(columns=['ticker', 'weights'])
        }
    
    # Step 3: Rank momentum-confirmed tickers by the last completed month's return.
    print("Step 3: Ranking bullish tickers by latest monthly return...")
    ranked_bullish_tickers = get_top_monthly_performers(
        raw_bullish_tickers,
        keep=len(raw_bullish_tickers),
        market_data=market_data,
    )
    top_performers = ranked_bullish_tickers[:num_signals]
    print(f"  Top {len(top_performers)} performers selected")
    
    if not top_performers:
        print("Warning: No top performers identified")
        return {
            'status': 'partial',
            'bullish_tickers': ranked_bullish_tickers,
            'bearish_tickers': bearish_tickers,
            'weights': pd.DataFrame(columns=['ticker', 'weights'])
        }
    
    # Step 4: Calculate portfolio weights
    print("Step 4: Calculating portfolio weights...")
    weights_df = port_opt(top_performers, lookback_months=lookback_months)
    print(f"  Calculated weights for {len(weights_df)} tickers")
    
    return {
        'status': 'success',
        'bullish_tickers': ranked_bullish_tickers,
        'bearish_tickers': bearish_tickers,
        'allocation_tickers': top_performers,
        'top_performers': top_performers,
        'market_data': market_data,
        'signals_data': signals_df,
        'weights': weights_df
    }
