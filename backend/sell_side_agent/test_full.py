#!/usr/bin/env python3
"""Invoke the deployed sell-side agent Lambda."""

import json
import os

import boto3


FUNCTION_NAME = os.getenv(
    "SELL_SIDE_LAMBDA_FUNCTION_NAME",
    "sidechart-sell-side-agent",
)


def test_sell_side_lambda() -> None:
    client = boto3.client("lambda")
    response = client.invoke(
        FunctionName=FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(
            {
                "topic": "Microsoft earnings and valuation",
                "tickers": ["MSFT"],
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
    test_sell_side_lambda()
