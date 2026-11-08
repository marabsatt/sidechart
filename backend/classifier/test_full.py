#!/usr/bin/env python3
"""Invoke the deployed classifier Lambda."""

import json
import os

import boto3


def test_classifier_lambda() -> None:
    client = boto3.client("lambda")
    response = client.invoke(
        FunctionName=os.getenv("CLASSIFIER_FUNCTION_NAME", "sidechart-classifier"),
        InvocationType="RequestResponse",
        Payload=json.dumps(
            {
                "instruments": [
                    {"symbol": "VTI", "name": "Vanguard Total Stock Market ETF"}
                ]
            }
        ),
    )
    payload = json.loads(response["Payload"].read())
    print(json.dumps(payload, indent=2))
    if response.get("FunctionError") or payload.get("statusCode") != 200:
        raise RuntimeError(f"Classifier Lambda failed: {payload}")


if __name__ == "__main__":
    test_classifier_lambda()
