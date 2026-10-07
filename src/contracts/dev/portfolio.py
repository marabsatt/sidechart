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


def get_top_performers(
    bullish_tickers: list,
    keep: int = 20,
    lookback_months: int = 1,
    lookback_days: int | None = None,
) -> list:
    '''
    Calculate returns for bullish tickers and return the top performers

    Args:
        bullish_tickers (list): List of ticker symbols identified as bullish
        keep (int): Number of top performers to return
        lookback_months (int): Number of months to look back for returns calculation
        lookback_days (int | None): Deprecated compatibility alias
    
    Returns:
        list: Top performing ticker symbols
    '''
    if not bullish_tickers:
        return []
    
    try:
        if lookback_days is not None:
            lookback_months = max(1, round(lookback_days / 30))
        start_date = (datetime.now() - timedelta(days=max(lookback_months, 1) * 31)).strftime('%Y-%m-%d')
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


def get_top_monthly_performers(
    tickers: list, keep: int = 20, market_data: pd.DataFrame | None = None
) -> list:
    '''
    Rank tickers by the return for the last completed calendar month.

    Args:
        tickers (list): Candidate ticker symbols, usually bullish tickers.
        keep (int): Maximum number of top performers to return.

    Returns:
        list: Tickers sorted by latest monthly return, highest first.
    '''
    if not tickers or keep <= 0:
        return []

    try:
        if market_data is None:
            market_data = get_market_data(tickers, period='5y', interval='1mo')
        if market_data.empty:
            return []

        returns_data = {}
        for ticker in tickers:
            ticker_data = market_data[market_data['ticker'] == ticker].copy()
            if ticker_data.empty:
                continue
            ticker_data['date'] = pd.to_datetime(ticker_data['date'], errors='coerce')
            ticker_data['close'] = pd.to_numeric(ticker_data['close'], errors='coerce')
            ticker_data = ticker_data.dropna(subset=['date', 'close']).sort_values('date')
            monthly_closes = ticker_data.groupby(ticker_data['date'].dt.to_period('M'))['close'].last()
            current_month = pd.Timestamp.now().to_period('M')
            completed_closes = monthly_closes[monthly_closes.index < current_month]
            if len(completed_closes) < 2:
                completed_closes = monthly_closes
            if len(completed_closes) < 2:
                continue

            previous_close = completed_closes.iloc[-2]
            latest_close = completed_closes.iloc[-1]
            if previous_close > 0:
                returns_data[ticker] = (latest_close - previous_close) / previous_close

        sorted_tickers = sorted(returns_data.items(), key=lambda item: item[1], reverse=True)
        top_tickers = [ticker for ticker, _ in sorted_tickers[:keep]]

        return top_tickers
    except Exception as e:
        print(f'Error calculating monthly top performers: {e}')
        return []
