#!/usr/bin/env python3
"""Invoke the deployed charter Lambda without the removed legacy database."""

import json
import os

import boto3


def test_charter_lambda() -> None:
    client = boto3.client("lambda")
    response = client.invoke(
        FunctionName=os.getenv("CHARTER_FUNCTION_NAME", "sidechart-charter"),
        InvocationType="RequestResponse",
        Payload=json.dumps(
            {
                "job_id": "deployed-charter-smoke-test",
                "portfolio_data": {
                    "accounts": [
                        {
                            "name": "IBKR Account",
                            "cash_balance": 5000,
                            "positions": [],
                        }
                    ]
                },
            }
        ),
    )
    payload = json.loads(response["Payload"].read())
    print(json.dumps(payload, indent=2))
    if response.get("FunctionError") or payload.get("statusCode") != 200:
        raise RuntimeError(f"Charter Lambda failed: {payload}")


if __name__ == "__main__":
    test_charter_lambda()
