import json
import unittest
from unittest.mock import AsyncMock, patch

import pandas as pd

from backend.supervisor_agent import lambda_handler
from backend.supervisor_agent.templates import supervisor_agent
from backend.supervisor_agent.tools import SUPERVISOR_TOOLS
from src.agents.supervisor.context import supervisor_agent as local_supervisor_agent
from src.agents.supervisor.tools import SUPERVISOR_TOOLS as LOCAL_SUPERVISOR_TOOLS


class SupervisorLambdaTests(unittest.TestCase):
    def test_templates_and_tools_are_the_local_agent_objects(self):
        self.assertIs(supervisor_agent, local_supervisor_agent)
        self.assertIs(SUPERVISOR_TOOLS, LOCAL_SUPERVISOR_TOOLS)

    @patch("contracts.dev.pipeline.run_analysis_pipeline")
    def test_fallback_instructions_use_yfinance_pipeline(self, run_pipeline):
        run_pipeline.return_value = {
            "status": "complete",
            "weights": pd.DataFrame({"ticker": ["MSFT"], "weights": [1.0]}),
            "bullish_tickers": ["MSFT"],
            "bearish_tickers": [],
        }

        instructions = supervisor_agent(
            tickers=["MSFT"],
            sellside_research="Research output",
            lookback_months=6,
            num_signals=1,
        )

        run_pipeline.assert_called_once_with(
            tickers=["MSFT"],
            lookback_months=6,
            num_signals=1,
        )
        self.assertIn("MSFT", instructions)

    @patch(
        "backend.supervisor_agent.lambda_handler.run_supervisor_agent",
        new_callable=AsyncMock,
    )
    def test_passes_pipeline_context_to_agent(self, run_agent):
        run_agent.return_value = {
            "agent": "supervisor_agent",
            "tickers": ["MSFT"],
            "output": "RebalanceProposal",
        }
        payload = {
            "tickers": ["MSFT"],
            "sellside_research": "Research output",
            "pipeline_results": {"status": "complete", "weights": []},
            "current_positions": [{"ticker": "MSFT", "position": 10}],
            "lookback_months": 6,
            "num_signals": 10,
            "task": "Review this portfolio.",
        }

        response = lambda_handler.lambda_handler(payload, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(json.loads(response["body"])["success"])
        run_agent.assert_awaited_once_with(
            tickers=["MSFT"],
            sellside_research="Research output",
            pipeline_results={"status": "complete", "weights": []},
            current_positions=[{"ticker": "MSFT", "position": 10}],
            lookback_months=6,
            num_signals=10,
            task="Review this portfolio.",
        )

    def test_rejects_nonpositive_pipeline_options(self):
        response = lambda_handler.lambda_handler({"num_signals": 0}, None)
        self.assertEqual(response["statusCode"], 400)


if __name__ == "__main__":
    unittest.main()
