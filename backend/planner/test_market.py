#!/usr/bin/env python3
"""Unit smoke test for planner market-price updates."""

from unittest.mock import Mock, patch

try:
    from .market import update_instrument_prices
except ImportError:
    from market import update_instrument_prices


def test_market_update() -> None:
    database = Mock()
    database.jobs.find_by_id.return_value = {"user_id": "user-1"}
    database.accounts.find_by_user.return_value = [{"id": "account-1"}]
    database.positions.find_by_account.return_value = [{"symbol": "AAPL"}]

    module_name = update_instrument_prices.__module__
    with patch(f"{module_name}.update_prices_for_symbols") as update_prices:
        update_instrument_prices("job-1", database)
        update_prices.assert_called_once_with({"AAPL"}, database)


if __name__ == "__main__":
    test_market_update()
    print("Planner market smoke test passed")
