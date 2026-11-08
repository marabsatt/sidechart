#!/usr/bin/env python3
"""Local smoke test for the charter Lambda handler."""

import json

try:
    from .lambda_handler import lambda_handler
except ImportError:
    from lambda_handler import lambda_handler


def test_charter() -> None:
    response = lambda_handler(
        {
            "job_id": "local-charter-smoke-test",
            "portfolio_data": {
                "accounts": [
                    {
                        "name": "IBKR Account",
                        "type": "brokerage",
                        "cash_balance": 5000,
                        "positions": [
                            {
                                "symbol": "SPY",
                                "quantity": 100,
                                "instrument": {
                                    "name": "SPDR S&P 500 ETF",
                                    "current_price": 450,
                                    "allocation_asset_class": {"equity": 100},
                                    "allocation_regions": {"north_america": 100},
                                    "allocation_sectors": {"technology": 100},
                                },
                            }
                        ],
                    }
                ]
            },
        },
        None,
    )
    print(json.dumps(response, indent=2))
    if response["statusCode"] != 200:
        raise RuntimeError(response["body"])


if __name__ == "__main__":
    test_charter()
