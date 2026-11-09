import unittest

from backend.check_jobs import records_as_dicts


class CheckJobsTests(unittest.TestCase):
    def test_records_as_dicts_uses_column_metadata(self):
        response = {
            "columnMetadata": [
                {"name": "signal_id"},
                {"name": "ticker"},
                {"name": "review_status"},
            ],
            "records": [
                [
                    {"stringValue": "signal-1"},
                    {"stringValue": "MSFT"},
                    {"isNull": True},
                ]
            ],
        }

        self.assertEqual(
            records_as_dicts(response),
            [
                {
                    "signal_id": "signal-1",
                    "ticker": "MSFT",
                    "review_status": None,
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
