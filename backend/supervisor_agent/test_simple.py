#!/usr/bin/env python3
"""Invoke the supervisor Lambda handler locally with supplied pipeline data."""

import json

try:
    from .lambda_handler import lambda_handler
except ImportError:
    from lambda_handler import lambda_handler


if __name__ == "__main__":
    response = lambda_handler(
        {
            "tickers": ["MSFT"],
            "sellside_research": "Microsoft research test context.",
            "pipeline_results": {
                "status": "complete",
                "weights": [{"ticker": "MSFT", "weights": 1.0}],
                "bullish_tickers": ["MSFT"],
                "bearish_tickers": [],
            },
            "current_positions": [{"ticker": "MSFT", "position": 10}],
        },
        None,
    )
    print(json.dumps(response, indent=2))
