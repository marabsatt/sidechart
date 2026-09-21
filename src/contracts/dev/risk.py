import riskfolio as rf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from .market_data import get_market_data


def _dedupe_tickers(tickers: list) -> list:
    seen = set()
    deduped = []
    for ticker in tickers:
        normalized = str(ticker).strip().upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _equal_weights(tickers: list) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame(columns=['ticker', 'weights'])

    equal_weight = 1.0 / len(tickers)
    return pd.DataFrame({
        'ticker': tickers,
        'weights': [equal_weight] * len(tickers)
    })


def _complete_weights(weights_df: pd.DataFrame, tickers: list) -> pd.DataFrame:
    if weights_df.empty:
        return _equal_weights(tickers)

    clean_weights = weights_df.copy()
    clean_weights['ticker'] = clean_weights['ticker'].astype(str).str.strip().str.upper()
    clean_weights['weights'] = pd.to_numeric(clean_weights['weights'], errors='coerce').fillna(0.0)
    clean_weights['weights'] = clean_weights['weights'].clip(lower=0.0)

    weight_map = clean_weights.groupby('ticker')['weights'].sum().to_dict()
    complete_df = pd.DataFrame({
        'ticker': tickers,
        'weights': [float(weight_map.get(ticker, 0.0)) for ticker in tickers]
    })

    total_weight = complete_df['weights'].sum()
    if total_weight <= 0:
        return _equal_weights(tickers)

    complete_df['weights'] = complete_df['weights'] / total_weight
    return complete_df.sort_values(['weights', 'ticker'], ascending=[False, True]).reset_index(drop=True)


def port_opt(tickers: list, lookback_days: int = 30) -> pd.DataFrame:
    '''
    Function used to calculate the portfolio weights using Sharpe as the maximizing objective

    Args: 
        tickers (list): List of ticker symbols to optimize
        lookback_days (int): Number of days to look back for returns calculation

    Return: 
        weights (pd.DataFrame): DataFrame with columns 'ticker' and 'weights' for portfolio allocation
    '''
    tickers = _dedupe_tickers(tickers)
    if not tickers:
        return pd.DataFrame(columns=['ticker', 'weights'])

    if len(tickers) == 1:
        return _equal_weights(tickers)
    
    try:
        start_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
        
        # Get market data for tickers
        market_data = get_market_data(tickers, start_date=start_date)
        
        if market_data.empty:
            return _equal_weights(tickers)
        
        # Pivot data to get close prices by ticker
        prices_pivot = market_data.pivot_table(
            index='date',
            columns='ticker',
            values='close'
        ).reindex(columns=tickers)
        prices_pivot = prices_pivot.dropna(axis=1, how='all').ffill().dropna()

        if len(prices_pivot.columns) == 1:
            return _complete_weights(
                pd.DataFrame({
                    'ticker': [prices_pivot.columns[0]],
                    'weights': [1.0]
                }),
                tickers
            )
        
        # Calculate returns
        port_returns = prices_pivot.pct_change().dropna()
        
        if port_returns.empty or len(port_returns) < 2:
            return _equal_weights(tickers)
        
        # Optimize portfolio
        port = rf.Portfolio(returns=port_returns)
        port.assets_stats(method_mu='hist', method_cov='ledoit')
        port.lowerret = .00056488 * 1.5
        
        weights = port.optimization(
            model='Classic',
            rm='MV',
            obj='Sharpe',
            hist=True
        )

        if weights is None or weights.empty:
            return _equal_weights(tickers)
        
        # Format output
        weights_df = pd.DataFrame({
            'ticker': weights.index,
            'weights': weights.values.flatten()
        })
        
        weights_df.loc[weights_df['weights'] < 0.01, 'weights'] = 0.0
        return _complete_weights(weights_df, tickers)
    
    except Exception as e:
        print(f'Error in portfolio optimization: {e}')
        return _equal_weights(tickers)
