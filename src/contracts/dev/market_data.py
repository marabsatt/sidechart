from __future__ import annotations

# Class for accessing financial data
import yfinance as yf

# Classes for Web scraping
import requests
from bs4 import BeautifulSoup

import pandas as pd


HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    )
}


def get_nasdaq_100_tickers() -> list:
    '''
    Function that retrieves all of the nasdaq 100 tickers from Wiki 

    Returns:
        list: A list of tickers symbols in the nasdaq 100 index
    '''
    url = "http://en.wikipedia.org/wiki/Nasdaq-100#Components"
    nasdaq_stocks = pd.Series(dtype=str)

    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()  # Raise an exception for HTTP errors
        html_content = response.text  # Print the HTML content of the page
        soup = BeautifulSoup(html_content, 'html.parser')
        table = soup.find('table', {'class': 'wikitable sortable'})
        company_ticker = pd.read_html(str(table))[0]
        nasdaq_stocks = company_ticker['Ticker']
        
    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL: {e}")

    nasdaq_ticker_list = nasdaq_stocks.tolist()
    return nasdaq_ticker_list

def get_sp500_tickers() -> list:
    '''
    Function that retrieves all of the S&P 500 tickers from Wiki 
    
    Returns:
        list: A list of tickers symbols in the S&P 500 index
    '''
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    sp_stocks = pd.Series(dtype=str)

    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()  # Raise an exception for HTTP errors
        html_content = response.text  # Print the HTML content of the page
        soup = BeautifulSoup(html_content, 'html.parser')
        tables = pd.read_html(str(soup))
        sp_stocks = tables[0]['Symbol']
    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL: {e}")

    sp_ticker_list = sp_stocks.tolist()

    # Changing the ticker format to match the format in Yahoo finance for the following BRK.B and BF.B
    if 'BRK.B' in sp_ticker_list:
        sp_ticker_list[sp_ticker_list.index('BRK.B')] = 'BRK-B'
    if 'BF.B' in sp_ticker_list:
        sp_ticker_list[sp_ticker_list.index('BF.B')] = 'BF-B'

    return sp_ticker_list


def _normalize_yfinance_frame(ticker: str, data: pd.DataFrame) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame(
            columns=['ticker', 'date', 'open', 'high', 'low', 'close', 'volume']
        )

    df = data.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            '_'.join(str(part) for part in column if part)
            for column in df.columns.to_flat_index()
        ]

    df = df.reset_index()
    rename_map = {}
    for column in df.columns:
        normalized = str(column).strip().lower().replace(' ', '_')
        if normalized in {'date', 'datetime'}:
            rename_map[column] = 'date'
        elif normalized.startswith('open'):
            rename_map[column] = 'open'
        elif normalized.startswith('high'):
            rename_map[column] = 'high'
        elif normalized.startswith('low'):
            rename_map[column] = 'low'
        elif normalized.startswith('close'):
            rename_map[column] = 'close'
        elif normalized.startswith('volume'):
            rename_map[column] = 'volume'

    df = df.rename(columns=rename_map)
    df['ticker'] = ticker

    columns = ['ticker', 'date', 'open', 'high', 'low', 'close', 'volume']
    for column in columns:
        if column not in df.columns:
            df[column] = None

    return df[columns]


def get_market_data(
    tickers: str | list | None,
    start_date: str | None = None,
    end_date: str | None = None,
    period: str = '3y',
    interval: str = '1mo',
) -> pd.DataFrame:
    '''
    Function that retrieves market data for a given ticker or a list of tickers using yfinance. If no tickers are provided, it retrieves all the data from the nasdaq 100 and s&p 500. 

    Args: 
        tickers (str|list): A ticker symbol or a list of tickers
        start_date (str|None): Optional start date in YYYY-MM-DD format
        end_date (str|None): Optional end date in YYYY-MM-DD format
        period (str): yfinance period used when start_date is not provided
        interval (str): yfinance interval

    Returns:
        pd.DataFrame: A normalized DataFrame containing market data for each ticker.
        Failed tickers are available in ``df.attrs['failed_tickers']``.
    '''
    if isinstance(tickers, str):
        tickers = [tickers]

    elif tickers is None:
        tickers = list(set(get_sp500_tickers() + get_nasdaq_100_tickers()))

    failed_tickers = []
    market_data = []
    for ticker in tickers:
        try:
            download_kwargs = {
                'interval': interval,
                'progress': False,
                'auto_adjust': False,
            }
            if start_date:
                download_kwargs['start'] = start_date
                if end_date:
                    download_kwargs['end'] = end_date
            else:
                download_kwargs['period'] = period

            ticker_data = yf.download(ticker, **download_kwargs)
            normalized_data = _normalize_yfinance_frame(ticker, ticker_data)
            if normalized_data.empty:
                failed_tickers.append((ticker, 'No market data returned'))
            else:
                market_data.append(normalized_data)

        except Exception as e:
            failed_tickers.append((ticker, str(e)))

    if market_data:
        market_data_df = pd.concat(market_data, ignore_index=True)
    else:
        market_data_df = pd.DataFrame(
            columns=['ticker', 'date', 'open', 'high', 'low', 'close', 'volume']
        )

    market_data_df.attrs['failed_tickers'] = failed_tickers
    return market_data_df
