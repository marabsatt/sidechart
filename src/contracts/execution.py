from time import monotonic
from typing import Optional

import pandas as pd
from ib_insync import IB, Trade

from .orders import buy_stock, sell_stock


FILLED_STATUS = 'Filled'
FAILED_STATUSES = {'ApiCancelled', 'Cancelled', 'Inactive'}


def _wait_for_fills(ib: IB, trades: list[Trade], timeout: float) -> None:
    '''Wait until every trade is filled or fail before submitting buys.'''
    deadline = monotonic() + timeout

    while not all(trade.orderStatus.status == FILLED_STATUS for trade in trades):
        failed_trades = [
            trade
            for trade in trades
            if trade.orderStatus.status in FAILED_STATUSES
        ]
        if failed_trades:
            statuses = [trade.orderStatus.status for trade in failed_trades]
            raise RuntimeError(f'Sell order failed with status: {statuses}')

        remaining = deadline - monotonic()
        if remaining <= 0:
            statuses = [trade.orderStatus.status for trade in trades]
            raise TimeoutError(f'Timed out waiting for sell orders: {statuses}')

        ib.waitOnUpdate(timeout=min(remaining, 1.0))


def execute_rebalance(
    ib: IB,
    target_weights: pd.DataFrame,
    account_value: Optional[float] = None,
    sell_timeout: float = 300.0,
) -> list[Trade]:
    '''Rebalance a paper account, waiting for all sells before buying.

    ``target_weights`` must contain ``ticker`` and ``weights`` columns, where
    weights are decimal portfolio fractions such as ``0.10`` for ten percent.
    The supplied ``ib`` instance must already be connected to the paper account.
    '''
    required_columns = {'ticker', 'weights'}
    missing_columns = required_columns.difference(target_weights.columns)
    if missing_columns:
        raise ValueError(f'target_weights is missing columns: {missing_columns}')
    if not ib.isConnected():
        raise ConnectionError('The supplied IB instance is not connected')

    positions = {
        position.contract.symbol: position
        for position in ib.positions()
        if position.position > 0
    }
    target = {
        row.ticker: float(row.weights)
        for row in target_weights[['ticker', 'weights']].itertuples(index=False)
    }

    if account_value is None:
        account_values = ib.accountValues()
        net_liquidation = next(
            (
                value.value
                for value in account_values
                if value.tag == 'NetLiquidation'
                and value.currency in {'USD', 'BASE'}
            ),
            None,
        )
        if net_liquidation is None:
            raise ValueError('Could not determine NetLiquidation from the account')
        account_value = float(net_liquidation)
    if account_value <= 0:
        raise ValueError('account_value must be greater than zero')

    sell_trades: list[Trade] = []
    buy_requests: list[tuple[str, float]] = []

    for ticker, position in positions.items():
        current_weight = float(position.position * position.avgCost) / account_value
        target_weight = target.get(ticker, 0.0)
        weight_delta = target_weight - current_weight

        if target_weight == 0.0:
            sell_trades.append(sell_stock(ib, ticker))
        elif weight_delta < 0:
            shares_to_sell = abs(weight_delta * account_value / position.avgCost)
            sell_trades.append(sell_stock(ib, ticker, shares_to_sell))
        elif weight_delta > 0:
            shares_to_buy = weight_delta * account_value / position.avgCost
            buy_requests.append((ticker, shares_to_buy))

    if sell_trades:
        _wait_for_fills(ib, sell_trades, sell_timeout)

    buy_trades = [
        buy_stock(ib, ticker, shares_to_buy)
        for ticker, shares_to_buy in buy_requests
    ]
    return sell_trades + buy_trades
