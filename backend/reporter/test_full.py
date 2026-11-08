#!/usr/bin/env python3
"""Invoke the deployed reporter Lambda without the removed legacy database."""

import json
import os

import boto3


def test_reporter_lambda() -> None:
    client = boto3.client("lambda")
    response = client.invoke(
        FunctionName=os.getenv("REPORTER_FUNCTION_NAME", "sidechart-reporter"),
        InvocationType="RequestResponse",
        Payload=json.dumps(
            {
                "job_id": "deployed-reporter-smoke-test",
                "portfolio_data": {
                    "accounts": [
                        {
                            "name": "IBKR Account",
                            "cash_balance": 5000,
                            "positions": [],
                        }
                    ]
                },
                "user_data": {},
            }
        ),
    )
    payload = json.loads(response["Payload"].read())
    print(json.dumps(payload, indent=2))
    if response.get("FunctionError") or payload.get("statusCode") != 200:
        raise RuntimeError(f"Reporter Lambda failed: {payload}")


if __name__ == "__main__":
    test_reporter_lambda()
