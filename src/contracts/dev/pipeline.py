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
    requested_tickers = list(dict.fromkeys(str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()))
    market_data = get_market_data(
        requested_tickers,
        period='5y',
        interval='1mo',
    )
    scanned = set(requested_tickers)

    if market_data.empty and requested_tickers:
        return {'status': 'failed', 'error': 'No market data retrieved'}

    discovery_tickers = [
        ticker for ticker in DEFAULT_DISCOVERY_TICKERS if ticker not in scanned
    ]
    remaining = discovery_tickers
    index_loaded = False

    bullish_tickers: list[str] = []
    bearish_tickers: list[str] = []
    signals_df = pd.DataFrame()
    top_performers: list[str] = []
    signal_candidates: list[str] = []
    next_batch = 0

    while True:
        available_tickers = list(dict.fromkeys(market_data['ticker'].dropna().tolist()))
        ranked_tickers = get_top_monthly_performers(
            available_tickers,
            keep=len(available_tickers),
            market_data=market_data,
        )
        signal_candidates = ranked_tickers
        signal_dates = pd.to_datetime(market_data['date'], errors='coerce')
        completed_market_data = market_data[
            signal_dates.dt.to_period('M') < pd.Timestamp.now().to_period('M')
        ]
        if completed_market_data.empty:
            completed_market_data = market_data
        raw_bullish_tickers, bearish_tickers, signals_df = signal_generator(completed_market_data)
        bullish_tickers = [ticker for ticker in ranked_tickers if ticker in raw_bullish_tickers]
        top_performers = bullish_tickers[:num_signals]

        if len(top_performers) >= num_signals:
            break

        if next_batch >= len(remaining):
            if index_loaded:
                break
            index_tickers = [
                ticker
                for ticker in dict.fromkeys(get_sp500_tickers() + get_nasdaq_100_tickers())
                if ticker not in scanned and ticker not in remaining
            ]
            remaining.extend(index_tickers)
            index_loaded = True
            if next_batch >= len(remaining):
                break

        batch = remaining[next_batch:next_batch + 40]
        next_batch += len(batch)
        if not batch:
            break
        additional_data = get_market_data(batch, period='5y', interval='1mo')
        scanned.update(batch)
        if not additional_data.empty:
            market_data = pd.concat([market_data, additional_data], ignore_index=True)

    print(f"Retrieved data for {market_data['ticker'].nunique()} tickers")
    print(f"  Monthly leaders screened: {len(signal_candidates)}")
    print(f"  Bullish tickers: {len(bullish_tickers)}")
    print(f"  Bearish tickers: {len(bearish_tickers)}")
    print("Step 3: Ranking bullish monthly leaders...")
    print(f"  Top {len(top_performers)} performers selected")
    
    if not top_performers:
        print("Warning: No top performers identified")
        return {
            'status': 'partial',
            'bullish_tickers': [],
            'screened_bullish_tickers': bullish_tickers,
            'bearish_tickers': bearish_tickers,
            'candidate_tickers': signal_candidates,
            'requested_positions': num_signals,
            'lookback_months': lookback_months,
            'market_data': market_data,
            'signals_data': signals_df,
            'weights': pd.DataFrame(columns=['ticker', 'weights'])
        }
    
    # Step 4: Calculate portfolio weights for the active universe.
    print("Step 4: Calculating portfolio weights...")
    allocation_tickers = list(dict.fromkeys(top_performers[:num_signals]))
    weights_df = port_opt(allocation_tickers, lookback_months=lookback_months)
    print(f"  Calculated weights for {len(weights_df)} tickers")
    
    return {
        'status': 'success' if len(allocation_tickers) == num_signals else 'partial',
        'bullish_tickers': allocation_tickers,
        'screened_bullish_tickers': bullish_tickers,
        'bearish_tickers': bearish_tickers,
        'candidate_tickers': signal_candidates,
        'requested_positions': num_signals,
        'lookback_months': lookback_months,
        'allocation_tickers': allocation_tickers,
        'top_performers': top_performers,
        'market_data': market_data,
        'signals_data': signals_df,
        'weights': weights_df
    }
