import unittest
from unittest.mock import Mock, patch

import pandas as pd

from backend.planner import market, prices


class PriceTests(unittest.TestCase):
    def test_normalizes_yahoo_class_share_symbol(self):
        self.assertEqual(prices._normalize_symbol(" brk.b "), "BRK-B")

    @patch("backend.planner.prices.yf.Ticker")
    def test_prefers_fast_info_last_price(self, ticker_factory):
        ticker_factory.return_value.fast_info = {"last_price": 123.45}

        self.assertEqual(prices.get_share_price_yfinance("aapl"), 123.45)
        ticker_factory.assert_called_once_with("AAPL")
        ticker_factory.return_value.history.assert_not_called()

    @patch("backend.planner.prices.yf.Ticker")
    def test_falls_back_to_latest_daily_close(self, ticker_factory):
        ticker_factory.return_value.fast_info = {}
        ticker_factory.return_value.history.return_value = pd.DataFrame(
            {"Close": [100.0, None, 105.25]}
        )

        self.assertEqual(prices.get_share_price_yfinance("MSFT"), 105.25)
        ticker_factory.return_value.history.assert_called_once_with(
            period="5d",
            interval="1d",
            auto_adjust=False,
            actions=False,
        )

    @patch("backend.planner.prices.get_share_price")
    def test_batch_prices_deduplicates_and_omits_missing_quotes(self, get_price):
        get_price.side_effect = lambda symbol: {"AAPL": 100.0, "MSFT": 0.0}[symbol]

        result = prices.get_share_prices(["aapl", "AAPL", "msft", ""])

        self.assertEqual(result, {"AAPL": 100.0})
        self.assertEqual(get_price.call_count, 2)

    @patch("backend.planner.prices.time.time", return_value=150.0)
    @patch("backend.planner.prices.yf.Ticker")
    def test_market_open_uses_regular_session_window(self, ticker_factory, _time):
        ticker_factory.return_value.get_history_metadata.return_value = {
            "currentTradingPeriod": {
                "regular": {
                    "start": pd.Timestamp(100, unit="s", tz="UTC"),
                    "end": pd.Timestamp(200, unit="s", tz="UTC"),
                }
            }
        }

        self.assertTrue(prices.is_market_open())


class MarketUpdateTests(unittest.TestCase):
    @patch("backend.planner.market.update_prices_for_symbols")
    def test_job_portfolio_lookup_uses_generic_user_id(self, update_prices):
        db = Mock()
        db.jobs.find_by_id.return_value = {"user_id": "user-123"}
        db.accounts.find_by_user.return_value = [{"id": "account-1"}]
        db.positions.find_by_account.return_value = [{"symbol": "AAPL"}]

        market.update_instrument_prices("job-1", db)

        db.accounts.find_by_user.assert_called_once_with("user-123")
        update_prices.assert_called_once_with({"AAPL"}, db)

    @patch("backend.planner.market.get_share_prices")
    def test_updates_only_quotes_returned_by_yfinance(self, get_prices):
        get_prices.return_value = {"AAPL": 123.45}
        db = Mock()
        db.instruments.find_by_symbol.return_value = {"symbol": "AAPL"}
        db.client.update.return_value = True

        market.update_prices_for_symbols({"aapl", "MSFT"}, db)

        get_prices.assert_called_once_with(["AAPL", "MSFT"])
        db.client.update.assert_called_once_with(
            "instruments",
            {"current_price": 123.45},
            "symbol = :symbol",
            {"symbol": "AAPL"},
        )


if __name__ == "__main__":
    unittest.main()
