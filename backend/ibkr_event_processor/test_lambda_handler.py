import json
import unittest
from unittest.mock import patch

from backend.ibkr_event_processor import lambda_handler as handler


class EventProcessorTests(unittest.TestCase):
    def test_connector_status_transitions(self):
        self.assertEqual(handler._connector_status("CONNECTED", {}), "CONNECTED")
        self.assertEqual(handler._connector_status("DISCONNECTED", {}), "DISCONNECTED")
        self.assertEqual(handler._connector_status("ERROR", {}), "DEGRADED")

    @patch.object(handler, "process_event")
    def test_reports_only_failed_sqs_records(self, process_event):
        process_event.side_effect = [None, ValueError("bad event")]
        event = {
            "Records": [
                {"messageId": "one", "body": json.dumps({"event_id": "one"})},
                {"messageId": "two", "body": json.dumps({"event_id": "two"})},
            ]
        }
        self.assertEqual(
            handler.lambda_handler(event, None),
            {"batchItemFailures": [{"itemIdentifier": "two"}]},
        )


if __name__ == "__main__":
    unittest.main()
