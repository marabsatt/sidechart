"""Small ib_insync wrapper; all IB Gateway access stays on this machine."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

from .config import ConnectorConfig
from .models import OrderCommand


class IbkrBroker:
    def __init__(self, config: ConnectorConfig):
        from ib_insync import IB

        self.config = config
        self.ib = IB()

    @property
    def connected(self) -> bool:
        return bool(self.ib.isConnected())

    def connect(self) -> None:
        if not self.connected:
            self.ib.connect(
                self.config.ib_host,
                self.config.ib_port,
                clientId=self.config.ib_client_id,
                timeout=8,
            )

    def disconnect(self) -> None:
        if self.connected:
            self.ib.disconnect()

    def wait(self, timeout: float = 0.25) -> None:
        if self.connected:
            self.ib.waitOnUpdate(timeout=timeout)

    def subscribe(
        self,
        *,
        order_status: Callable[..., None],
        execution: Callable[..., None],
        commission: Callable[..., None],
        position: Callable[..., None],
        error: Callable[..., None],
        disconnected: Callable[..., None],
    ) -> None:
        self.ib.orderStatusEvent += order_status
        self.ib.execDetailsEvent += execution
        self.ib.commissionReportEvent += commission
        self.ib.positionEvent += position
        self.ib.errorEvent += error
        self.ib.disconnectedEvent += disconnected

    def find_trade(self, command_id: str) -> Any | None:
        for trade in self.ib.trades():
            if str(getattr(trade.order, "orderRef", "")) == command_id:
                return trade
        return None

    def place_order(self, command: OrderCommand) -> Any:
        from ib_insync import LimitOrder, MarketOrder, Stock, StopOrder

        contract = Stock(command.ticker.upper(), "SMART", "USD")
        qualified = self.ib.qualifyContracts(contract)
        if not qualified:
            raise RuntimeError(f"IBKR could not qualify {command.ticker}")

        quantity = int(command.quantity)
        if command.order_type == "MKT":
            order = MarketOrder(command.action, quantity)
        elif command.order_type == "LMT":
            order = LimitOrder(command.action, quantity, float(Decimal(str(command.limit_price))))
        else:
            order = StopOrder(command.action, quantity, float(Decimal(str(command.stop_price))))
        order.orderRef = command.command_id
        order.tif = "DAY"
        trade = self.ib.placeOrder(qualified[0], order)
        self.ib.sleep(0.25)
        return trade
