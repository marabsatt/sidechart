#!/usr/bin/env python3
"""Invoke the sell-side Lambda handler locally with a small request."""

import json

try:
    from .lambda_handler import lambda_handler
except ImportError:
    from lambda_handler import lambda_handler


if __name__ == "__main__":
    response = lambda_handler(
        {"topic": "Microsoft earnings and valuation", "tickers": ["MSFT"]},
        None,
    )
    print(json.dumps(response, indent=2))
