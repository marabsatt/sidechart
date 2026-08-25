import os
import pandas as pd
import numpy as np
from massive import RESTClient
from dotenv import load_dotenv
from datetime import datetime

load_dotenv(override=True)

polygon_api_key = os.getenv("POLYGON_API_KEY")
client = RESTClient(polygon_api_key)

# Check to see if the market is open

def is_market_open() -> bool:
    '''
    Function that checks the market status using Massive's RESTClient
    
    Returns:
        open — The regular trading session is active.
        closed — The market or exchange is closed for the day or weekend.
        extended-hours (pre-market / post-market) — Operating during early bird or after-hours trading sessions.
        early-close — Used typically in holiday schedules when an exchange closes ahead of standard times.
    '''
    market_status = client.get_market_status()
    print(f'Market status: {market_status.market}')
    return market_status.market

def get_market_data(ticker: str, start_date: str, end_date: str = datetime.now().strftime('%Y-%m-%d')) -> pd.DataFrame:
    '''
    Function that retrieves market data for a given ticker symbol bewtween a specified start and end date

    Args:
        ticker (str): The ticker symbol of the stock or asset.
        start_date (str): The start date for the data retrieval in 'YYYY-MM-DD' format.
        end_date (str): The end date for the data retrieval in 'YYYY-MM-DD' format. Defaults to the current date if not provided.
    
    Returns:
        pd.DataFrame: A DataFrame containing the market (timestamp, open, high, low, close, volume) data for the specified ticker and date range.
    '''
    bars = client.get_aggs(ticker, 1, "day", start_date, end_date)
    data = []
    for bar in bars:
        data.append({
            "timestamp": datetime.fromtimestamp(bar.timestamp / 1000),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume
        })
    return pd.DataFrame(data)

def get_nasdaq_tickers() -> list:
    '''
    Function that retrieves a list of all NASDAQ tickers
    
    Returns:
        list: A list of ticker symbols for all NASDAQ-listed companies
    '''
    tickers = client.list_tickers(exchange = 'XNAS', market = 'stocks', limit = 1000)
    nasdaq_tickers = [ticker.ticker for ticker in tickers]
    return nasdaq_tickers

def get_nyse_tickers() -> list:
    '''
    Function that retrieves a list of all NYSE tickers
    
    Returns:
        list: A list of ticker symbols for all NYSE-listed companies
    '''
    tickers = client.list_tickers(exchange = 'XNYS', market = 'stocks', limit=1000)
    nyse_tickers = [ticker.ticker for ticker in tickers]
    return nyse_tickers


def get_amex_tickers() -> list:
    '''
    Function that retrieves a list of all AMEX tickers
    
    Returns:
        list: A list of ticker symbols for all AMEX-listed companies
    '''
    tickers = client.list_tickers(exchange = 'XASE', market = 'stocks', limit=1000)
    amex_tickers = [ticker.ticker for ticker in tickers]
    return amex_tickers


def get_cboe_tickers() -> list:
    '''
    Function that retrieves a list of all CBOE tickers
    
    Returns:
        list: A list of ticker symbols for all CBOE-listed companies
    '''
    tickers = client.list_tickers(exchange = 'BATS', market="Indices", limit=1000)
    cboe_tickers = [ticker.ticker for ticker in tickers]
    return cboe_tickers

def get_latest_price(ticker: str) -> float:
    '''
    Function that retrieves the latest price for a given ticker symbol
    
    Args:
        ticker (str): The ticker symbol of the stock
        
    Returns:
        float: The latest price of the stock
    '''
    quote = client.get_quote(ticker)
    return quote.last.price