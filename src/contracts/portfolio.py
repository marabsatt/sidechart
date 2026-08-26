import pandas as pd
import numpy as np

def pflio(DF: pd.DataFrame, m: int, x: int) -> list:
    '''
    Function to calculate the cumulative portfolio return per month

    Args:
        DF: Dataframe with monthly return info for all stocks
        m: Number of stocks to keep in the portfolio
        x: Number of underperforming stocks to be removed from portfolio monthly
    
    Returns:
        portfolio: List tickers to add to the portfolio based on the monthly returns
    '''
    df = DF.copy()
    portfolio = []
    monthly_ret = [0]
    for i in range(len(df)):
        if len(portfolio) > 0:
            monthly_ret.append(df[portfolio].iloc[i,:].mean())
            low_return_stocks = df[portfolio].iloc[i,:].sort_values(ascending=True)[:x].index.values.tolist()
            portfolio = [t for t in portfolio if t not in low_return_stocks]
        fill = m - len(portfolio)
        new_picks = df.iloc[i,:].sort_values(ascending=False)[:fill].index.values.tolist()
        portfolio = portfolio + new_picks
        # print('\n list of stocks to go long: \n', portfolio)
    return portfolio