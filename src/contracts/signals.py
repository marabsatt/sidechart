import pandas as pd
import numpy as np

FAST_RSI_PERIOD = 5
SLOW_RSI_PERIOD = 15
FAST_EMA_PERIOD = 5
SLOW_EMA_PERIOD = 15
MACD_FAST_PERIOD = 12
MACD_SLOW_PERIOD = 26
MACD_SIGNAL_PERIOD = 9
MIN_SIGNAL_ROWS = MACD_SLOW_PERIOD + MACD_SIGNAL_PERIOD - 1


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

    required_columns = {'ticker', 'date', 'close'}
    missing_columns = required_columns.difference(market_data.columns)
    if missing_columns:
        raise ValueError(f"market_data missing required columns: {sorted(missing_columns)}")
    
    bullish_tickers = []
    bearish_tickers = []
    signals_list = []

    prepared_data = market_data.copy()
    prepared_data['close'] = pd.to_numeric(prepared_data['close'], errors='coerce')
    if 'volume' in prepared_data.columns:
        prepared_data['volume'] = pd.to_numeric(prepared_data['volume'], errors='coerce')
    else:
        prepared_data['volume'] = np.nan
    
    # Process each ticker separately
    for ticker in prepared_data['ticker'].dropna().unique():
        ticker_data = prepared_data[prepared_data['ticker'] == ticker].copy()
        ticker_data = ticker_data.sort_values('date')
        ticker_data = ticker_data.dropna(subset=['close'])
        
        if len(ticker_data) < MIN_SIGNAL_ROWS:
            ticker_data['_Signal'] = 'bearish'
            bearish_tickers.append(ticker)
            signals_list.append(ticker_data)
            continue
        
        try:
            # Calculate indicators
            ticker_data['_FAST_RSI'] = rsi(ticker_data['close'], periods=FAST_RSI_PERIOD)
            ticker_data['_SLOW_RSI'] = rsi(ticker_data['close'], periods=SLOW_RSI_PERIOD)
            ticker_data['_MACD'], ticker_data['_Signal_Line'], ticker_data['_MACD_Hist'] = macd(
                ticker_data['close'],
                fast_period=MACD_FAST_PERIOD,
                slow_period=MACD_SLOW_PERIOD,
                signal_period=MACD_SIGNAL_PERIOD,
            )
            ticker_data['_EMA_5'] = ema(ticker_data['close'], period=FAST_EMA_PERIOD)
            ticker_data['_EMA_15'] = ema(ticker_data['close'], period=SLOW_EMA_PERIOD)
            ticker_data['_prev_volume'] = ticker_data['volume'].shift(1)
            ticker_data['_avg_volume_3m'] = ticker_data['volume'].ewm(span=3, adjust=False).mean()
            
            # Get the latest row
            latest = ticker_data.iloc[-1]
            prev = ticker_data.iloc[-2] if len(ticker_data) > 1 else ticker_data.iloc[-1]

            indicator_columns = [
                '_EMA_5',
                '_EMA_15',
                '_FAST_RSI',
                '_SLOW_RSI',
                '_MACD',
                '_Signal_Line',
                '_MACD_Hist',
                'close',
            ]
            has_indicators = all(pd.notna(latest[column]) for column in indicator_columns)
            
            # Determine if the stock is bullish based on technical indicators
            trend_confirmation = latest['_EMA_5'] > latest['_EMA_15']
            rsi_confirmation = (
                latest['_FAST_RSI'] >= latest['_SLOW_RSI'] and
                latest['_FAST_RSI'] > 50
            )
            macd_confirmation = (
                latest['_MACD'] > latest['_Signal_Line'] and
                latest['_MACD_Hist'] > 0
            )
            price_confirmation = latest['close'] > prev['close']
            volume_confirmation = (
                pd.notna(latest['volume']) and
                pd.notna(latest['_avg_volume_3m']) and
                latest['volume'] >= latest['_avg_volume_3m']
            )
            confirmation_count = sum(
                [
                    rsi_confirmation,
                    macd_confirmation,
                    volume_confirmation,
                ]
            )
            is_bullish = (
                has_indicators and
                trend_confirmation and
                price_confirmation and
                confirmation_count >= 2
            )
            ticker_data['_Signal'] = 'bearish'
            
            if is_bullish:
                bullish_tickers.append(ticker)
                ticker_data.loc[ticker_data.index[-1], '_Signal'] = 'bullish'
            else:
                bearish_tickers.append(ticker)
            
            signals_list.append(ticker_data)
        except Exception as e:
            print(f'Error processing signals for {ticker}: {e}')
            bearish_tickers.append(ticker)
    
    signals_df = pd.concat(signals_list, ignore_index=True) if signals_list else pd.DataFrame()
    return bullish_tickers, bearish_tickers, signals_df
