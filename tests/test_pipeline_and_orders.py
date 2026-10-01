import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pandas as pd

from backend import server
from contracts.dev import pipeline
from contracts.dev.risk import _complete_weights


class PipelineSelectionTests(unittest.TestCase):
    def test_selected_positions_keep_positive_trade_weights(self):
        raw = pd.DataFrame({"ticker": ["A", "B", "C"], "weights": [0.8, 0.2, 0.0]})
        result = _complete_weights(raw, ["A", "B", "C"])

        self.assertEqual(len(result), 3)
        self.assertTrue((result["weights"] >= 0.01).all())
        self.assertAlmostEqual(result["weights"].sum(), 1.0)

    def test_expands_universe_and_ranks_only_bullish_tickers(self):
        closes = {"B1": 115, "B2": 120, "B3": 130, "X": 150}

        def market_data(tickers, **_kwargs):
            rows = [
                {"ticker": ticker, "date": date, "close": close}
                for ticker in tickers
                for date, close in (
                    ("2026-07-31", 100),
                    ("2026-08-31", 110),
                    ("2026-09-30", closes[ticker]),
                )
            ]
            return pd.DataFrame(rows, columns=["ticker", "date", "close"])

        def signals(df):
            symbols = df["ticker"].unique().tolist()
            bullish = [ticker for ticker in symbols if ticker.startswith("B")]
            bearish = [ticker for ticker in symbols if ticker not in bullish]
            return bullish, bearish, df

        def weights(tickers, **_kwargs):
            return pd.DataFrame({
                "ticker": tickers,
                "weights": [1 / len(tickers)] * len(tickers),
            })

        with (
            patch.object(pipeline, "get_market_data", side_effect=market_data),
            patch.object(pipeline, "signal_generator", side_effect=signals),
            patch.object(pipeline, "DEFAULT_DISCOVERY_TICKERS", ["B2", "B3"]),
            patch.object(pipeline, "port_opt", side_effect=weights),
        ):
            result = pipeline.run_analysis_pipeline(["B1", "X"], num_signals=2)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["bullish_tickers"], ["B3", "B2"])
        self.assertEqual(result["allocation_tickers"], ["B3", "B2"])
        self.assertEqual(result["screened_bullish_tickers"], ["B1", "B2", "B3"])
        self.assertEqual(result["weights"]["ticker"].tolist(), ["B3", "B2"])

    def test_scans_later_index_batches_to_fill_positions(self):
        def market_data(tickers, **_kwargs):
            return pd.DataFrame([
                {"ticker": ticker, "date": date, "close": close}
                for ticker in tickers
                for date, close in (
                    ("2026-07-31", 100),
                    ("2026-08-31", 110),
                    ("2026-09-30", 120),
                )
            ], columns=["ticker", "date", "close"])

        def signals(df):
            symbols = df["ticker"].unique().tolist()
            bullish = [ticker for ticker in symbols if ticker.startswith("B")]
            return bullish, [ticker for ticker in symbols if ticker not in bullish], df

        index = [f"X{i}" for i in range(40)] + ["B1", "B2"]
        with (
            patch.object(pipeline, "get_market_data", side_effect=market_data),
            patch.object(pipeline, "signal_generator", side_effect=signals),
            patch.object(pipeline, "DEFAULT_DISCOVERY_TICKERS", []),
            patch.object(pipeline, "get_sp500_tickers", return_value=index),
            patch.object(pipeline, "get_nasdaq_100_tickers", return_value=[]),
            patch.object(pipeline, "port_opt", return_value=pd.DataFrame({
                "ticker": ["B1", "B2"], "weights": [0.5, 0.5]
            })),
        ):
            result = pipeline.run_analysis_pipeline([], num_signals=2)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["bullish_tickers"], ["B1", "B2"])


class WeightedOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_endpoint_uses_async_ibkr_session(self):
        status = {
            "connected": True,
            "mode": "Trader Workstation",
            "host": "127.0.0.1",
            "port": 7497,
        }
        with patch.object(server, "_connect_shared_ib", new_callable=AsyncMock, return_value=status) as connect:
            response = await server.connect_ibkr(
                server.BrokerConnectRequest(ports=[7497], timeout=1)
            )

        connect.assert_awaited_once_with("127.0.0.1", 7497, 17, 4.0)
        self.assertTrue(response["connected"])

    async def test_order_uses_account_balance_and_returns_ibkr_order_id(self):
        class FakeIB:
            def __init__(self):
                self.submitted = None

            def isConnected(self):
                return True

            async def accountSummaryAsync(self):
                return []

            def accountValues(self):
                return [SimpleNamespace(tag="NetLiquidation", currency="USD", value="10000")]

            async def qualifyContractsAsync(self, contract):
                return [contract]

            def reqMarketDataType(self, _market_data_type):
                pass

            async def reqTickersAsync(self, _contract):
                return [SimpleNamespace(marketPrice=lambda: 100)]

            def placeOrder(self, contract, order):
                order.orderId = 123
                self.submitted = (contract, order)
                return SimpleNamespace(
                    contract=contract,
                    order=order,
                    orderStatus=SimpleNamespace(status="Submitted", filled=0, remaining=25),
                    log=[],
                )

        fake_ib = FakeIB()
        with patch.object(server, "IB_CONNECTION", fake_ib):
            preview = await server.buy_order(
                server.OrderRequest(ticker="NVDA", target_weight=0.25, dry_run=True)
            )
            self.assertIsNone(fake_ib.submitted)
            response = await server.buy_order(
                server.OrderRequest(ticker="NVDA", target_weight=0.25, dry_run=False)
            )

        self.assertEqual(preview["order"]["quantity"], 25)
        self.assertEqual(fake_ib.submitted[1].totalQuantity, 25)
        self.assertEqual(fake_ib.submitted[1].action, "BUY")
        self.assertEqual(response["trade"]["order_id"], 123)
        self.assertEqual(response["trade"]["status"], "Submitted")
        self.assertEqual(response["sizing"]["target_notional"], 2500)


if __name__ == "__main__":
    unittest.main()
