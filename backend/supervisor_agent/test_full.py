#!/usr/bin/env python3
"""Invoke the deployed supervisor agent Lambda."""

import json
import os

import boto3


FUNCTION_NAME = os.getenv(
    "SUPERVISOR_LAMBDA_FUNCTION_NAME",
    "sidechart-supervisor-agent",
)


def test_supervisor_lambda() -> None:
    client = boto3.client("lambda")
    response = client.invoke(
        FunctionName=FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(
            {
                "tickers": ["MSFT"],
                "sellside_research": "Microsoft research test context.",
                "pipeline_results": {
                    "status": "complete",
                    "weights": [{"ticker": "MSFT", "weights": 1.0}],
                    "bullish_tickers": ["MSFT"],
                    "bearish_tickers": [],
                },
                "current_positions": [
                    {"ticker": "MSFT", "position": 10}
                ],
            }
        ),
    )
    payload = json.loads(response["Payload"].read())
    print(json.dumps(payload, indent=2))

    if response.get("FunctionError"):
        raise RuntimeError(f"Lambda failed: {payload}")
    if payload.get("statusCode") != 200:
        raise RuntimeError(f"Unexpected Lambda response: {payload}")


if __name__ == "__main__":
    test_supervisor_lambda()
