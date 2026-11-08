#!/usr/bin/env python3
"""Import and input-validation smoke test for the planner handler."""

import json

try:
    from .lambda_handler import lambda_handler
except ImportError:
    from lambda_handler import lambda_handler


def test_planner() -> None:
    response = lambda_handler({}, None)
    print(json.dumps(response, indent=2))
    if response["statusCode"] != 400:
        raise RuntimeError(f"Unexpected planner response: {response}")


if __name__ == "__main__":
    test_planner()
