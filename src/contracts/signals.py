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
    """
    Calculates the MACD and Signal Line from a price Series.

    Args:
        data (pd.Series): Series containing closing prices.
        fast_period (int): Fast EMA period.
        slow_period (int): Slow EMA period.
        signal_period (int): Signal line EMA period.

    Returns:
        pd.Series, pd.Series: MACD line and Signal line.
    """
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
    """
    Calculates the Exponential Moving Average (EMA) for a given price Series.

    Args:
        data (pd.Series): Series containing closing prices.
        period (int): The number of periods to use for the EMA calculation.

    Returns:
        pd.Series: EMA values.
    """
    ema = data.ewm(span = period, adjust = False).mean()
    return ema

bullish_df = pd.DataFrame()
bearish_df = pd.DataFrame()
error_dic = {}
def signal_generator(data: pd.DataFrame) -> pd.DataFrame:
    '''
    Generates trading signals based on RSI, MACD, and EMA indicators.

    Args:
        data (pd.DataFrame): A pandas DataFrame containing the price data with a 'close' column.

    Returns:
        pd.DataFrame: A pandas Dataframe containing the original data along with the generated signals.
    '''

    # Using Fast and Slow RSI as a leading indicator to confirm momentum
    data['_FAST_RSI'] = rsi(data['close'], periods = 5)
    data['_SLOW_RSI'] = rsi(data['close'], periods = 15)

    # Using MACD as a lagging indicator to confirm momentum
    data['_MACD'], data['_Signal_Line'], data['_MACD_Hist'] = macd(data['close'])

    # Using Exponential Moving Average to determine Stocks that have upward momentum
    data['_EMA_5'] = ema(data['close'], period = 5)
    data['_EMA_15'] = ema(data['close'], period = 15)

    data['_prev_volume'] = data['volume'].shift(1)
    data['_avg_volume_3m'] = data['volume'].ewm(span = 3, adjust = False).mean()

    for ticker in data['ticker']:
        try:
            # Determine if the stock is bullish or bearish based on EMA crossover
            condition = (
                # Checking for short term bullish trend
                (data[f'{ticker}_EMA_5'] > data[f'{ticker}_EMA_15']) \
                # Checking for upward momentum via RSI and MACD
                & (data[f'{ticker}_FAST_RSI'] > data[f'{ticker}_SLOW_RSI']) \
                & (data[f'{ticker}_MACD'] > data[f'{ticker}_Signal_Line']) \
                # Confirming the strength of the trend via MACD histogram
                & (data[f'{ticker}_MACD_Hist'] > 0) & (data[f'{ticker}_MACD_Hist'].diff() > 0) \
                # Confirming the price action is making either higher highs or higher lows
                & (data[f'{ticker}'].iloc[-1] > data[f'{ticker}'].iloc[-2]) \
                # Confirming increased trading volume to avoid false signals
                & (data[f'{ticker}_prev_volume'] > data[f'{ticker}_avg_volume_3m'])
            )

            if condition.iloc[-1] == True:
                bullish_ticker = data[data[f'{ticker}']]
                pd.concat(bullish_df, bullish_ticker, ignore_index = True)
            else:
                bearish_ticker = data[data[f'{ticker}']]
                pd.concat(bearish_df, bearish_ticker, ignore_index = True)
        except Exception as e:
            error_dic.update({f'{ticker}': e})

    return bullish_df, bearish_df