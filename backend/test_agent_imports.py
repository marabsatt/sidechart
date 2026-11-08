"""Regression tests for running agent modules from their own directories."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import AsyncMock, patch

from backend.charter.lambda_handler import lambda_handler as charter_handler
from backend.classifier.lambda_handler import lambda_handler as classifier_handler
from backend.planner.lambda_handler import lambda_handler as planner_handler
from backend.reporter.lambda_handler import lambda_handler as reporter_handler
from backend.sell_side_agent.lambda_handler import lambda_handler as sell_side_handler
from backend.supervisor_agent.lambda_handler import lambda_handler as supervisor_handler


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
AGENTS = (
    "classifier",
    "charter",
    "planner",
    "reporter",
    "sell_side_agent",
    "supervisor_agent",
)


class AgentImportTests(unittest.TestCase):
    def test_handlers_import_from_their_agent_directories(self):
        for agent_name in AGENTS:
            with self.subTest(agent=agent_name):
                result = subprocess.run(
                    [sys.executable, "-c", "import lambda_handler"],
                    cwd=REPOSITORY_ROOT / "backend" / agent_name,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_validation_paths_do_not_require_legacy_database_package(self):
        responses = (
            classifier_handler({}, None),
            charter_handler({"job_id": "job-1"}, None),
            planner_handler({}, None),
            reporter_handler({"job_id": "job-1"}, None),
            sell_side_handler({"tickers": "MSFT"}, None),
            supervisor_handler({"tickers": "MSFT"}, None),
        )
        self.assertTrue(all(response["statusCode"] == 400 for response in responses))

    @patch(
        "backend.classifier.lambda_handler.process_instruments",
        new_callable=AsyncMock,
    )
    def test_classifier_success_path_has_no_database_import(self, process_instruments):
        process_instruments.return_value = {
            "tagged": 1,
            "updated": [],
            "errors": [],
            "persistence": "not_applicable",
            "classifications": [{"symbol": "VTI"}],
        }
        response = classifier_handler(
            {"instruments": [{"symbol": "VTI", "name": "Vanguard ETF"}]},
            None,
        )
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["tagged"], 1)


if __name__ == "__main__":
    unittest.main()
