# Class for accessing financial data
import yfinance as yf

# Classes for Web scraping
import requests
from bs4 import BeautifulSoup

import pandas as pd
import numpy as np

def get_nasdaq_100_tickers() -> list:
    '''
    Function that retrieves all of the nasdaq 100 tickers from Wiki 

    Returns:
        list: A list of tickers symbols in the nasdaq 100 index
    '''
    url = "http://en.wikipedia.org/wiki/Nasdaq-100#Components"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

    try:
        response = requests.get(url, headers=headers)
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
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Raise an exception for HTTP errors
        html_content = response.text  # Print the HTML content of the page
        soup = BeautifulSoup(html_content, 'html.parser')
        tables = pd.read_html(str(soup))
        sp_stocks = tables[0]['Symbol']
    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL: {e}")

    sp_ticker_list = sp_stocks.tolist()

    # Changing the ticker format to match the format in Yahoo finance for the following BRK.B and BF.B
    sp_ticker_list[sp_ticker_list.index('BRK.B')] = 'BRK-B'
    sp_ticker_list[sp_ticker_list.index('BF.B')] = 'BF-B'

    return sp_ticker_list

def get_market_data(tickers: str|list) -> pd.DataFrame:
    '''
    Function that retrieves market data for a given ticker or a list of tickers using yfinance. If no tickers are provided, it retrieves all the data from the nasdaq 100 and s&p 500. 

    Args: 
        tickers (str|list): A ticker symbol or a list of tickers

    Returns:
        pd.DataFrame: A DataFrame containing the market data for each ticker
        list: A list of tickers that failed to retrieve data
    '''
    if isinstance(tickers, str):
        tickers = [tickers]

    elif tickers is None:
        tickers = list(set(get_sp500_tickers() + get_nasdaq_100_tickers()))

    failed_tickers = []
    for ticker in tickers:
        try:
            market_data_df = yf.download(ticker, period = '3y', interval = '1mo')

        except Exception as e:
            failed_tickers.append((ticker, e))

    return market_data_df, failed_tickers