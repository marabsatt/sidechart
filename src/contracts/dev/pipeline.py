"""
Data pipeline orchestrator for the trading system.

Pipeline flow:
1. market_data → gather OHLCV data for multiple tickers
2. signals → identify bullish/bearish tickers
3. portfolio → calculate returns for bullish tickers, select top performers
4. risk → optimize portfolio weights using the active universe
5. execution → execute trades using the calculated weights
"""

import pandas as pd
from datetime import datetime, timedelta

from .market_data import (
    DEFAULT_DISCOVERY_TICKERS,
    get_market_data,
    get_nasdaq_100_tickers,
    get_sp500_tickers,
)
from ..signals import signal_generator
from .portfolio import get_top_monthly_performers
from .risk import port_opt


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
    signal_lookback_days = max(lookback_days, 120)
    start_date = (datetime.now() - timedelta(days=signal_lookback_days)).strftime('%Y-%m-%d')
    requested_tickers = list(dict.fromkeys(str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()))
    market_data = get_market_data(requested_tickers, start_date=start_date, interval='1d')
    
    bullish_tickers, bearish_tickers, signals_df = signal_generator(market_data)
    scanned = set(requested_tickers)
    if len(bullish_tickers) < num_signals:
        discovery_tickers = [ticker for ticker in DEFAULT_DISCOVERY_TICKERS if ticker not in scanned]
        if discovery_tickers:
            additional_data = get_market_data(discovery_tickers, start_date=start_date, interval='1d')
            scanned.update(discovery_tickers)
            if not additional_data.empty:
                market_data = pd.concat([market_data, additional_data], ignore_index=True)
                bullish_tickers, bearish_tickers, signals_df = signal_generator(market_data)

    if len(bullish_tickers) < num_signals:
        remaining = [
            ticker for ticker in dict.fromkeys(get_sp500_tickers() + get_nasdaq_100_tickers())
            if ticker not in scanned
        ]
        for offset in range(0, len(remaining), 40):
            if len(bullish_tickers) >= num_signals:
                break
            batch = remaining[offset:offset + 40]
            additional_data = get_market_data(batch, start_date=start_date, interval='1d')
            scanned.update(batch)
            if not additional_data.empty:
                market_data = pd.concat([market_data, additional_data], ignore_index=True)
                bullish_tickers, bearish_tickers, signals_df = signal_generator(market_data)

    if market_data.empty:
        return {'status': 'failed', 'error': 'No market data retrieved'}

    print(f"Retrieved data for {market_data['ticker'].nunique()} tickers")
    print(f"  Bullish tickers: {len(bullish_tickers)}")
    print(f"  Bearish tickers: {len(bearish_tickers)}")
    
    # Step 3: Rank bullish tickers by latest monthly return.
    print("Step 3: Ranking bullish tickers by latest monthly return...")
    top_performers = get_top_monthly_performers(
        bullish_tickers, keep=num_signals, market_data=market_data
    )
    print(f"  Top {len(top_performers)} performers selected")
    
    if not top_performers:
        print("Warning: No top performers identified")
        return {
            'status': 'partial',
            'bullish_tickers': [],
            'screened_bullish_tickers': bullish_tickers,
            'bearish_tickers': bearish_tickers,
            'candidate_tickers': bullish_tickers,
            'requested_positions': num_signals,
            'market_data': market_data,
            'signals_data': signals_df,
            'weights': pd.DataFrame(columns=['ticker', 'weights'])
        }
    
    # Step 4: Calculate portfolio weights for the active universe.
    print("Step 4: Calculating portfolio weights...")
    allocation_tickers = list(dict.fromkeys(top_performers[:num_signals]))
    weights_df = port_opt(allocation_tickers, lookback_days=lookback_days)
    print(f"  Calculated weights for {len(weights_df)} tickers")
    
    return {
        'status': 'success' if len(allocation_tickers) == num_signals else 'partial',
        'bullish_tickers': allocation_tickers,
        'screened_bullish_tickers': bullish_tickers,
        'bearish_tickers': bearish_tickers,
        'candidate_tickers': bullish_tickers,
        'requested_positions': num_signals,
        'allocation_tickers': allocation_tickers,
        'top_performers': top_performers,
        'market_data': market_data,
        'signals_data': signals_df,
        'weights': weights_df
    }
