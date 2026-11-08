#!/usr/bin/env python3
"""Check that the deployed planner Lambda loads and validates its event."""

import json
import os

import boto3


def test_planner_lambda() -> None:
    client = boto3.client("lambda")
    response = client.invoke(
        FunctionName=os.getenv("PLANNER_FUNCTION_NAME", "sidechart-planner"),
        InvocationType="RequestResponse",
        Payload=json.dumps({}),
    )
    payload = json.loads(response["Payload"].read())
    print(json.dumps(payload, indent=2))
    if response.get("FunctionError") or payload.get("statusCode") != 400:
        raise RuntimeError(f"Unexpected planner Lambda response: {payload}")


if __name__ == "__main__":
    test_planner_lambda()
