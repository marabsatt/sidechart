import random
import nest_asyncio
from ib_insync import IB

def get_current_holdings() -> list: 
    '''
    Functiion to retrieve current holdings from IBKR

    Returns:
        list: A list of current positions held in the IBKR account
    '''
    nest_asyncio.apply()
    # Connect to IBKR
    ib = IB()
    # For Paper Trading with IB TWS
    ib.connect('127.0.0.1', 7497, clientId = random.randint(1,99))
    # For Paper Trading with IB Gateway
    #ib.connect('127.0.0.1', 4002, clientId=random.randint(1, 99))

    # Get current positions
    positions = ib.positions()
    return positions