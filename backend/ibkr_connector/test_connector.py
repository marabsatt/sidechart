from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from backend.ibkr_connector.config import ConnectorConfig
from backend.ibkr_connector.journal import Journal
from backend.ibkr_connector.models import OrderCommand, utc_now
from backend.ibkr_connector.service import ConnectorService


def command_payload(**overrides):
    payload = {
        "schema_version": 1,
        "command_id": str(uuid.uuid4()),
        "order_id": str(uuid.uuid4()),
        "supervisor_review_id": str(uuid.uuid4()),
        "account_mode": "PAPER",
        "ticker": "AAPL",
        "action": "BUY",
        "order_type": "LMT",
        "quantity": 2,
        "limit_price": "200.00",
        "created_at": utc_now().isoformat(),
        "expires_at": (utc_now() + timedelta(minutes=5)).isoformat(),
    }
    payload.update(overrides)
    return payload


class FakeQueues:
    def __init__(self):
        self.events = []
        self.deleted = []

    def publish_event(self, event):
        self.events.append(event)

    def delete_command(self, receipt):
        self.deleted.append(receipt)


class FakeStatus:
    status = "Submitted"
    filled = 0


class FakeOrder:
    orderId = 123
    permId = 456


class FakeTrade:
    order = FakeOrder()
    orderStatus = FakeStatus()


class FakeBroker:
    connected = True

    def subscribe(self, **callbacks):
        self.callbacks = callbacks

    def place_order(self, command):
        self.command = command
        self.trade = FakeTrade()
        self.trade.order.orderRef = command.command_id
        return self.trade

    def find_trade(self, command_id):
        return None


class ConnectorTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.config = ConnectorConfig(
            command_queue_url="commands",
            event_queue_url="events",
            journal_path=root / "journal.sqlite3",
            kill_switch_path=root / "kill-switch",
        )
        self.queues = FakeQueues()
        self.broker = FakeBroker()
        self.journal = Journal(self.config.journal_path)
        self.service = ConnectorService(
            self.config, queues=self.queues, broker=self.broker, journal=self.journal
        )

    def tearDown(self):
        self.service.executor.shutdown(wait=False, cancel_futures=True)
        self.journal.close()
        self.tempdir.cleanup()

    def test_validates_limit_order(self):
        command = OrderCommand.from_dict(command_payload())
        self.assertEqual(command.ticker, "AAPL")

    def test_rejects_expired_command(self):
        with self.assertRaisesRegex(ValueError, "expired"):
            OrderCommand.from_dict(
                command_payload(expires_at=(utc_now() - timedelta(seconds=1)).isoformat())
            )

    def test_places_and_journals_command_before_deleting_message(self):
        payload = command_payload()
        self.service.process_message({"Body": json.dumps(payload), "ReceiptHandle": "receipt-1"})

        self.assertEqual(self.journal.command_state(payload["command_id"]), "ACKNOWLEDGED")
        self.assertEqual(self.queues.deleted, ["receipt-1"])
        self.assertIn("ORDER_ACK", [event["event_type"] for event in self.queues.events])

    def test_kill_switch_rejects_command(self):
        self.config.kill_switch_path.touch()
        payload = command_payload()
        self.service.process_message({"Body": json.dumps(payload), "ReceiptHandle": "receipt-2"})
        self.assertEqual(self.journal.command_state(payload["command_id"]), "REJECTED")
        self.assertEqual(self.broker.__dict__.get("command"), None)


if __name__ == "__main__":
    unittest.main()
