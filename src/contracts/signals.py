import pandas as pd
import numpy as np

def rsi(data: pd.Series, periods: int) -> pd.Series:
    '''
    Function that calculates the Relative Strength Index (RSI) for a given pandas series.

    Args:
        data (pd.Series): A pandas series containing the price data (e.g., closing prices).
        periods (int): The number of periods to use for the RSI calculation 
    
    Returns: 
        pd.Series: A pandas series containing the RSI values.
    '''

    # Calculate price changes
    price_diff = data.diff()

    # Separate gains and losses
    gain = price_diff.clip(lower=0)  # Only positive changes are gains
    loss = -1 * price_diff.clip(upper=0) # Only negative changes are losses, converted to positive

    # Calculate average gain and loss using a rolling mean
    # The first 'periods' values will be NaN as there isn't enough data for a full window
    avg_gain = gain.ewm(com=periods-1, adjust=False).mean() # Exponentially Weighted Moving Average
    avg_loss = loss.ewm(com=periods-1, adjust=False).mean()

    # Calculate Relative Strength (RS)
    rs = avg_gain / avg_loss

    # Calculate RSI
    rsi = 100 - (100 / (1 + rs))

    return rsi

def macd(data: pd.Series, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9) -> pd.Series:
    '''
    Calculates the MACD and Signal Line from a price Series.

    Args:
        data (pd.Series): Series containing closing prices.
        fast_period (int): Fast EMA period.
        slow_period (int): Slow EMA period.
        signal_period (int): Signal line EMA period.

    Returns:
        pd.Series, pd.Series: MACD line and Signal line.
    '''
    ema_fast = data.ewm(span=fast_period, adjust=False, min_periods=fast_period).mean()
    ema_slow = data.ewm(span=slow_period, adjust=False, min_periods=slow_period).mean()

    # Calculate the MACD Line
    macd_line = ema_fast - ema_slow
    # Calculate the MACD Signal Line
    signal_line = macd_line.ewm(span=signal_period, adjust=False, min_periods=signal_period).mean()
    # Calculate the MACD Histogram
    macd_histogram = macd_line - signal_line

    return macd_line, signal_line, macd_histogram

def ema(data: pd.Series, period: int) -> pd.Series:
    '''
    Calculates the Exponential Moving Average (EMA) for a given price Series.

    Args:
        data (pd.Series): Series containing closing prices.
        period (int): The number of periods to use for the EMA calculation.

    Returns:
        pd.Series: EMA values.
    '''
    ema = data.ewm(span = period, adjust = False).mean()
    return ema

def signal_generator(market_data: pd.DataFrame) -> tuple:
    '''
    Generates trading signals based on RSI, MACD, and EMA indicators.

    Args:
        market_data (pd.DataFrame): A DataFrame with columns: ticker, date, close, volume, etc.

    Returns:
        tuple: (bullish_tickers, bearish_tickers, signals_df) where tickers are lists of symbols
    '''
    if market_data.empty:
        return [], [], pd.DataFrame()
    
    bullish_tickers = []
    bearish_tickers = []
    signals_list = []
    
    # Process each ticker separately
    for ticker in market_data['ticker'].unique():
        ticker_data = market_data[market_data['ticker'] == ticker].copy()
        ticker_data = ticker_data.sort_values('date')
        
        if len(ticker_data) < 15:  # Need minimum data for indicators
            continue
        
        try:
            # Calculate indicators
            ticker_data['_FAST_RSI'] = rsi(ticker_data['close'], periods=5)
            ticker_data['_SLOW_RSI'] = rsi(ticker_data['close'], periods=15)
            ticker_data['_MACD'], ticker_data['_Signal_Line'], ticker_data['_MACD_Hist'] = macd(ticker_data['close'])
            ticker_data['_EMA_5'] = ema(ticker_data['close'], period=5)
            ticker_data['_EMA_15'] = ema(ticker_data['close'], period=15)
            ticker_data['_prev_volume'] = ticker_data['volume'].shift(1)
            ticker_data['_avg_volume_3m'] = ticker_data['volume'].ewm(span=3, adjust=False).mean()
            
            # Get the latest row
            latest = ticker_data.iloc[-1]
            prev = ticker_data.iloc[-2] if len(ticker_data) > 1 else ticker_data.iloc[-1]
            
            # Determine if the stock is bullish based on technical indicators
            is_bullish = (
                (latest['_EMA_5'] > latest['_EMA_15']) and  # Short term bullish trend
                (latest['_FAST_RSI'] > latest['_SLOW_RSI']) and  # Upward momentum
                (latest['_MACD'] > latest['_Signal_Line']) and  # MACD positive
                (latest['_MACD_Hist'] > 0) and  # Histogram positive
                (latest['close'] > prev['close']) and  # Price increasing
                (latest['volume'] > latest['_avg_volume_3m'])  # Volume confirmation
            )
            
            if is_bullish:
                bullish_tickers.append(ticker)
            else:
                bearish_tickers.append(ticker)
            
            signals_list.append(ticker_data)
        except Exception as e:
            print(f'Error processing signals for {ticker}: {e}')
            bearish_tickers.append(ticker)
    
    signals_df = pd.concat(signals_list, ignore_index=True) if signals_list else pd.DataFrame()
    return bullish_tickers, bearish_tickers, signals_df