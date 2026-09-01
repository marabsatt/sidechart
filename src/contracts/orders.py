import math
from ib_insync import IB, Order, Stock

def buy_stock(ib: IB, long_ticker: str, buy_diff: float):
        '''
        Function to place purchase orders with IBKR

        Args:
            long_ticker (str): Ticker symbol used to establish a long position
            buy_diff (float): The number of shares to purchase

        Returns:
            Trade: The submitted IBKR trade handle
        '''
        stock = Stock(
            symbol = long_ticker, 
            exchange = 'SMART', 
            currency = 'USD'
        )
        
        action = Order(
            action = 'BUY',
            totalQuantity = math.ceil(buy_diff),
            orderType = 'MKT',
            tif = 'GTC',
            outsideRth = True
        )
        
        return ib.placeOrder(stock, action)

def sell_stock(ib: IB, ticker: str, sell_diff: float = None):
        '''
        Function to place sell orders with IBKR

        Args:
            ticker (str): Ticker symbol used to establish a long position
            sell_diff (float): The amount difference to sell based on the calculated weight if a position is already established

        Returns:
            Trade: The submitted IBKR trade handle
        '''
        stock = Stock(
            symbol = ticker, 
            exchange = 'SMART', 
            currency = 'USD'
        )
        
        for i in range (len(ib.positions())):
            if ib.positions()[i].contract.symbol == ticker:
                sell_amount = ib.positions()[i].position

        if sell_diff is None:
            action = Order(
                action = 'SELL', 
                totalQuantity = sell_amount, 
                orderType = 'MKT',  
                tif = 'GTC', 
                outsideRth = True
            )
        else:
            action = Order(
                action = 'SELL', 
                totalQuantity = math.ceil(sell_diff), 
                orderType = 'MKT',  
                tif = 'GTC', 
                outsideRth = True
            ) 
        
        return ib.placeOrder(stock, action)