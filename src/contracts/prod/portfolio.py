import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from .market_data import get_market_data


def pflio(DF: pd.DataFrame, keep: int, remove: int) -> list:
    '''
    Function to calculate the cumulative portfolio return per month

    Args:
        DF: Dataframe with monthly return info for all stocks
        keep: Number of stocks to keep in the portfolio
        remove: Number of underperforming stocks to be removed from portfolio monthly
    
    Returns:
        portfolio: List tickers to add to the portfolio based on the monthly returns
    '''
    if DF.empty or keep <= 0:
        return []
    
    df = DF.copy()
    portfolio = []
    monthly_ret = [0]
    
    for i in range(len(df)):
        if len(portfolio) > 0:
            monthly_ret.append(df[portfolio].iloc[i,:].mean())
            low_return_stocks = df[portfolio].iloc[i,:].sort_values(ascending=True)[:remove].index.values.tolist()
            portfolio = [t for t in portfolio if t not in low_return_stocks]
        fill = keep - len(portfolio)
        new_picks = df.iloc[i,:].sort_values(ascending=False)[:fill].index.values.tolist()
        portfolio = portfolio + new_picks
    
    return portfolio


def get_top_performers(bullish_tickers: list, keep: int = 20, lookback_days: int = 30) -> list:
    '''
    Calculate returns for bullish tickers and return the top performers

    Args:
        bullish_tickers (list): List of ticker symbols identified as bullish
        keep (int): Number of top performers to return
        lookback_days (int): Number of days to look back for returns calculation
    
    Returns:
        list: Top performing ticker symbols
    '''
    if not bullish_tickers:
        return []
    
    try:
        start_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
        market_data = get_market_data(bullish_tickers, start_date=start_date)
        
        if market_data.empty:
            return bullish_tickers[:keep]
        
        # Calculate returns for each ticker
        returns_data = {}
        for ticker in bullish_tickers:
            ticker_data = market_data[market_data['ticker'] == ticker]
            if not ticker_data.empty:
                first_price = ticker_data['close'].iloc[0]
                last_price = ticker_data['close'].iloc[-1]
                if first_price > 0:
                    returns_data[ticker] = (last_price - first_price) / first_price
        
        # Sort by returns and return top performers
        sorted_tickers = sorted(returns_data.items(), key=lambda x: x[1], reverse=True)
        top_tickers = [ticker for ticker, _ in sorted_tickers[:keep]]
        
        return top_tickers if top_tickers else bullish_tickers[:keep]
    except Exception as e:
        print(f'Error calculating top performers: {e}')
        return bullish_tickers[:keep]