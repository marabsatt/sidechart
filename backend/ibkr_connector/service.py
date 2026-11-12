"""Long-running outbound-only connector service."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import json
import logging
import signal
import threading
from time import monotonic
from typing import Any

from . import __version__
from .aws_queues import AwsQueues
from .broker import IbkrBroker
from .config import ConnectorConfig
from .journal import Journal
from .models import BrokerEvent, OrderCommand


LOGGER = logging.getLogger("sidechart.ibkr_connector")


class ConnectorService:
    def __init__(
        self,
        config: ConnectorConfig,
        queues: AwsQueues | None = None,
        broker: IbkrBroker | None = None,
        journal: Journal | None = None,
    ):
        config.validate()
        self.config = config
        self.queues = queues or AwsQueues(config)
        self.broker = broker or IbkrBroker(config)
        self.journal = journal or Journal(config.journal_path)
        self.stop_event = threading.Event()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqs-poll")
        self.receive_future: Future[dict[str, Any] | None] | None = None
        self.last_heartbeat = 0.0
        self.broker.subscribe(
            order_status=self._on_order_status,
            execution=self._on_execution,
            commission=self._on_commission,
            position=self._on_position,
            error=self._on_error,
            disconnected=self._on_disconnected,
        )

    def emit(self, event_type: str, payload: dict[str, Any], order_id: str | None = None) -> None:
        payload = {
            "account_mode": self.config.account_mode,
            "gateway_port": self.config.ib_port,
            "client_id": self.config.ib_client_id,
            "version": __version__,
            **payload,
        }
        event = BrokerEvent(
            connector_id=self.config.connector_id,
            event_type=event_type,
            order_id=order_id,
            payload=payload,
        )
        self.journal.enqueue_event(event.to_dict())

    def flush_events(self) -> None:
        for event in self.journal.pending_events():
            try:
                self.queues.publish_event(event)
            except Exception:
                LOGGER.exception("Unable to publish broker event %s", event["event_id"])
                return
            self.journal.mark_event_sent(event["event_id"])

    def process_message(self, message: dict[str, Any]) -> None:
        receipt = message["ReceiptHandle"]
        try:
            raw = json.loads(message["Body"])
            command = OrderCommand.from_dict(raw)
        except Exception as exc:
            self.emit("COMMAND_REJECTED", {"reason": str(exc)})
            self.flush_events()
            self.queues.delete_command(receipt)
            return

        if command.account_mode != self.config.account_mode:
            self._reject(command, receipt, "Command account mode does not match connector")
            return
        if command.quantity > self.config.max_order_quantity:
            self._reject(command, receipt, "Quantity exceeds local connector limit")
            return
        if self.config.kill_switch_path.exists():
            self._reject(command, receipt, "Local kill switch is active")
            return

        previous_state = self.journal.command_state(command.command_id)
        if previous_state in {"ACKNOWLEDGED", "REJECTED", "BLOCKED"}:
            self.queues.delete_command(receipt)
            return
        if previous_state == "SUBMITTING":
            trade = self.broker.find_trade(command.command_id)
            if trade is None:
                self.journal.set_command_state(command.command_id, "BLOCKED", "Ambiguous replay")
                self.emit(
                    "MANUAL_RECONCILIATION_REQUIRED",
                    {"command_id": command.command_id, "reason": "Submission state is ambiguous"},
                    command.order_id,
                )
            else:
                self._acknowledge(command, trade)
            self.flush_events()
            self.queues.delete_command(receipt)
            return

        self.journal.record_command(command.command_id, command.order_id, raw)
        try:
            trade = self.broker.place_order(command)
            status = str(getattr(trade.orderStatus, "status", ""))
            if status in {"Inactive", "Cancelled", "ApiCancelled"}:
                raise RuntimeError(f"IBKR rejected order with status {status}")
            self._acknowledge(command, trade)
            self.flush_events()
            self.queues.delete_command(receipt)
        except Exception as exc:
            self.journal.set_command_state(command.command_id, "REJECTED", str(exc))
            self.emit(
                "ORDER_REJECTED",
                {"command_id": command.command_id, "reason": str(exc)},
                command.order_id,
            )
            self.flush_events()
            self.queues.delete_command(receipt)

    def _acknowledge(self, command: OrderCommand, trade: Any) -> None:
        order = trade.order
        status = trade.orderStatus
        self.emit(
            "ORDER_ACK",
            {
                "command_id": command.command_id,
                "ib_order_id": getattr(order, "orderId", None),
                "ib_perm_id": getattr(order, "permId", None) or None,
                "status": getattr(status, "status", None) or "Submitted",
                "filled_qty": int(getattr(status, "filled", 0) or 0),
            },
            command.order_id,
        )
        self.journal.set_command_state(command.command_id, "ACKNOWLEDGED")

    def _reject(self, command: OrderCommand, receipt: str, reason: str) -> None:
        self.journal.record_command(command.command_id, command.order_id, command.__dict__)
        self.journal.set_command_state(command.command_id, "REJECTED", reason)
        self.emit("COMMAND_REJECTED", {"command_id": command.command_id, "reason": reason}, command.order_id)
        self.flush_events()
        self.queues.delete_command(receipt)

    def _order_context(self, trade: Any) -> tuple[str | None, str | None]:
        command_id = str(getattr(trade.order, "orderRef", "") or "") or None
        return command_id, self.journal.order_id_for_command(command_id) if command_id else None

    def _on_order_status(self, trade: Any) -> None:
        command_id, order_id = self._order_context(trade)
        status = trade.orderStatus
        self.emit("ORDER_STATUS", {
            "command_id": command_id,
            "ib_order_id": getattr(trade.order, "orderId", None),
            "ib_perm_id": getattr(trade.order, "permId", None) or None,
            "status": getattr(status, "status", None),
            "filled_qty": int(getattr(status, "filled", 0) or 0),
            "remaining_qty": int(getattr(status, "remaining", 0) or 0),
            "average_fill_price": getattr(status, "avgFillPrice", None),
        }, order_id)

    def _on_execution(self, trade: Any, fill: Any) -> None:
        command_id, order_id = self._order_context(trade)
        execution = fill.execution
        self.emit("EXECUTION", {
            "command_id": command_id,
            "ib_exec_id": execution.execId,
            "ib_order_id": execution.orderId,
            "ib_perm_id": execution.permId,
            "price": execution.price,
            "shares": int(execution.shares),
            "executed_at": execution.time.isoformat(),
        }, order_id)

    def _on_commission(self, trade: Any, fill: Any, report: Any) -> None:
        _, order_id = self._order_context(trade)
        self.emit("COMMISSION", {
            "ib_exec_id": report.execId,
            "commission": report.commission,
            "currency": report.currency,
            "realized_pnl": report.realizedPNL,
        }, order_id)

    def _on_position(self, position: Any) -> None:
        self.emit("POSITION", {
            "ticker": position.contract.symbol,
            "position_size": int(position.position),
            "average_cost": position.avgCost,
        })

    def _on_error(self, request_id: int, error_code: int, error_string: str, contract: Any = None) -> None:
        self.emit("ERROR", {"request_id": request_id, "code": error_code, "message": error_string})

    def _on_disconnected(self) -> None:
        self.emit("DISCONNECTED", {"gateway_port": self.config.ib_port})

    def _heartbeat(self) -> None:
        self.emit("HEARTBEAT", {
            "status": "CONNECTED" if self.broker.connected else "DISCONNECTED",
            "account_mode": self.config.account_mode,
            "gateway_port": self.config.ib_port,
            "client_id": self.config.ib_client_id,
            "version": __version__,
        })
        self.last_heartbeat = monotonic()

    def run(self) -> None:
        signal.signal(signal.SIGTERM, lambda *_: self.stop_event.set())
        signal.signal(signal.SIGINT, lambda *_: self.stop_event.set())
        try:
            self.broker.connect()
            self.emit("CONNECTED", {"account_mode": self.config.account_mode, "gateway_port": self.config.ib_port})
            while not self.stop_event.is_set():
                self.broker.wait()
                if monotonic() - self.last_heartbeat >= self.config.heartbeat_seconds:
                    self._heartbeat()
                self.flush_events()
                if self.receive_future is None:
                    self.receive_future = self.executor.submit(self.queues.receive_command)
                elif self.receive_future.done():
                    message = self.receive_future.result()
                    self.receive_future = None
                    if message:
                        self.process_message(message)
        finally:
            self.emit("DISCONNECTED", {"reason": "connector stopped"})
            self.flush_events()
            self.broker.disconnect()
            self.executor.shutdown(wait=False, cancel_futures=True)
            self.journal.close()
