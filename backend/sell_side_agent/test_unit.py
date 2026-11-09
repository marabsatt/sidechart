import json
import unittest
from unittest.mock import AsyncMock, patch

import pandas as pd

from backend.sell_side_agent import lambda_handler
from backend.sell_side_agent.templates import (
    DEFAULT_RESEARCH_PROMPT,
    sellside_agent_instructions,
)
from src.agents.research.context import (
    DEFAULT_RESEARCH_PROMPT as LOCAL_DEFAULT_RESEARCH_PROMPT,
    sellside_agent_instructions as local_sellside_agent_instructions,
)


class SellSideLambdaTests(unittest.TestCase):
    def test_templates_are_the_local_agent_templates(self):
        self.assertIs(DEFAULT_RESEARCH_PROMPT, LOCAL_DEFAULT_RESEARCH_PROMPT)
        self.assertIs(sellside_agent_instructions, local_sellside_agent_instructions)

    @patch("contracts.dev.pipeline.run_analysis_pipeline")
    def test_instructions_use_yfinance_pipeline(self, run_pipeline):
        run_pipeline.return_value = {
            "weights": pd.DataFrame({"ticker": ["MSFT"], "weights": [1.0]})
        }

        instructions = sellside_agent_instructions(["MSFT"])

        run_pipeline.assert_called_once_with(tickers=["MSFT"], num_signals=1)
        self.assertIn("MSFT", instructions)

    @patch(
        "backend.sell_side_agent.lambda_handler.run_sell_side_agent",
        new_callable=AsyncMock,
    )
    def test_accepts_api_gateway_body(self, run_agent):
        run_agent.return_value = {
            "agent": "sell_side_agent",
            "tickers": ["MSFT"],
            "output": "Research output",
        }

        response = lambda_handler.lambda_handler(
            {"body": json.dumps({"topic": "Microsoft", "tickers": ["MSFT"]})},
            None,
        )

        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(json.loads(response["body"])["success"])
        run_agent.assert_awaited_once_with(topic="Microsoft", tickers=["MSFT"])

    def test_rejects_non_array_tickers(self):
        response = lambda_handler.lambda_handler({"tickers": "MSFT"}, None)
        self.assertEqual(response["statusCode"], 400)


if __name__ == "__main__":
    unittest.main()
