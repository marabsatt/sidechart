import json
import unittest
from unittest.mock import patch

from backend.ibkr_order_api import lambda_handler as handler


class ApprovedOrderApiTests(unittest.TestCase):
    def test_rejects_invalid_review_id(self):
        response = handler.lambda_handler(
            {"body": json.dumps({"supervisor_review_id": "not-a-uuid"})}, None
        )
        self.assertEqual(response["statusCode"], 400)

    @patch.object(handler, "create_approved_order")
    def test_returns_accepted_for_new_order(self, create):
        create.return_value = (
            {"order_id": "order-1", "status": "QUEUED"},
            True,
        )
        response = handler.lambda_handler(
            {
                "body": json.dumps(
                    {"supervisor_review_id": "8ef1b931-b164-4d58-b93e-ff10b8109cdd"}
                )
            },
            None,
        )
        self.assertEqual(response["statusCode"], 202)
        self.assertTrue(json.loads(response["body"])["queued"])

    @patch.object(handler, "create_approved_order")
    def test_returns_existing_order_idempotently(self, create):
        create.return_value = (
            {"order_id": "order-1", "status": "Submitted"},
            False,
        )
        response = handler.lambda_handler(
            {
                "body": json.dumps(
                    {"supervisor_review_id": "8ef1b931-b164-4d58-b93e-ff10b8109cdd"}
                )
            },
            None,
        )
        self.assertEqual(response["statusCode"], 200)
        self.assertFalse(json.loads(response["body"])["queued"])


if __name__ == "__main__":
    unittest.main()
