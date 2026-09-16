import riskfolio as rf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from .market_data import get_market_data

def port_opt(tickers: list, lookback_days: int = 30) -> pd.DataFrame:
    '''
    Function used to calculate the portfolio weights using Sharpe as the maximizing objective

    Args: 
        tickers (list): List of ticker symbols to optimize
        lookback_days (int): Number of days to look back for returns calculation

    Return: 
        weights (pd.DataFrame): DataFrame with columns 'ticker' and 'weights' for portfolio allocation
    '''
    if not tickers:
        return pd.DataFrame(columns=['ticker', 'weights'])
    
    try:
        start_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
        
        # Get market data for tickers
        market_data = get_market_data(tickers, start_date=start_date)
        
        if market_data.empty:
            # Return equal weights if no data
            equal_weight = 1.0 / len(tickers)
            return pd.DataFrame({
                'ticker': tickers,
                'weights': [equal_weight] * len(tickers)
            })
        
        # Pivot data to get close prices by ticker
        prices_pivot = market_data.pivot_table(
            index='date',
            columns='ticker',
            values='close'
        )
        
        # Calculate returns
        port_returns = prices_pivot.pct_change().dropna()
        
        if port_returns.empty or len(port_returns) < 2:
            # Return equal weights if insufficient data
            equal_weight = 1.0 / len(tickers)
            return pd.DataFrame({
                'ticker': tickers,
                'weights': [equal_weight] * len(tickers)
            })
        
        # Factor indices for multi-factor model
        factors = ['MTUM', 'QUAL', 'VLUE', 'SIZE', 'USMV']
        try:
            factors_data = get_market_data(factors, start_date=start_date)
            factors_pivot = factors_data.pivot_table(
                index='date',
                columns='ticker',
                values='close'
            )
            factors_returns = factors_pivot.pct_change().dropna()
        except:
            factors_returns = None
        
        # Optimize portfolio
        port = rf.Portfolio(returns=port_returns)
        port.assets_stats(method_mu='hist', method_cov='ledoit')
        port.lowerret = .00056488 * 1.5
        
        if factors_returns is not None and not factors_returns.empty:
            try:
                loadings = rf.loadings_matrix(
                    X=factors_returns,
                    Y=port_returns,
                    feature_selection='PCR',
                    n_components=0.95
                )
            except:
                loadings = None
        else:
            loadings = None
        
        weights = port.optimization(
            model='FM' if loadings is not None else 'Classic',
            rm='MV',
            obj='Sharpe',
            hist=True
        )
        
        # Format output
        weights_df = pd.DataFrame({
            'ticker': weights.index,
            'weights': weights.values.flatten()
        })
        
        # Filter out very small weights and normalize
        weights_df = weights_df[weights_df['weights'] >= 0.01].copy()
        if weights_df.empty:
            weights_df = weights_df[weights_df['weights'] > 0].copy()
        
        if not weights_df.empty:
            weights_df['weights'] = weights_df['weights'] / weights_df['weights'].sum()
            weights_df = weights_df.sort_values('weights', ascending=False)
        
        return weights_df
    
    except Exception as e:
        print(f'Error in portfolio optimization: {e}')
        # Return equal weights as fallback
        equal_weight = 1.0 / len(tickers)
        return pd.DataFrame({
            'ticker': tickers,
            'weights': [equal_weight] * len(tickers)
        })