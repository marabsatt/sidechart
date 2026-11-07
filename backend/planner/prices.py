"""Yahoo Finance price helpers for the planner service."""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Iterable
from typing import Any

import pandas as pd
import yfinance as yf


logger = logging.getLogger(__name__)
MARKET_STATUS_SYMBOL = "^GSPC"


def _normalize_symbol(symbol: str) -> str:
    """Normalize a ticker to the format expected by Yahoo Finance."""
    normalized = str(symbol).strip().upper()
    if not normalized:
        raise ValueError("A non-empty ticker symbol is required.")
    return normalized.replace(".", "-")


def _positive_price(value: Any) -> float | None:
    """Return a finite positive float or ``None`` for unusable quote values."""
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(price) or price <= 0:
        return None
    return price


def _latest_close(history: pd.DataFrame) -> float | None:
    """Extract the newest valid close from a yfinance history frame."""
    if history.empty or "Close" not in history.columns:
        return None
    closes = history["Close"].dropna()
    if closes.empty:
        return None
    return _positive_price(closes.iloc[-1])


def _epoch_seconds(value: Any) -> float:
    """Convert yfinance epoch values or pandas timestamps to epoch seconds."""
    timestamp_method = getattr(value, "timestamp", None)
    if callable(timestamp_method):
        return float(timestamp_method())
    return float(value)


def is_market_open() -> bool:
    """Return whether the current time falls in the regular US trading session."""
    try:
        metadata = yf.Ticker(MARKET_STATUS_SYMBOL).get_history_metadata()
        regular_session = metadata.get("currentTradingPeriod", {}).get("regular", {})
        session_start = regular_session.get("start")
        session_end = regular_session.get("end")
        if session_start is None or session_end is None:
            logger.warning("Yahoo Finance did not return a regular trading session.")
            return False
        return _epoch_seconds(session_start) <= time.time() < _epoch_seconds(session_end)
    except Exception as exc:
        logger.warning("Could not determine market status from Yahoo Finance: %s", exc)
        return False


def get_share_price_yfinance(symbol: str) -> float:
    """Return the latest available Yahoo Finance price for one symbol.

    The low-latency ``fast_info`` quote is preferred. Daily history is used as
    a fallback for symbols or environments where that quote is unavailable.
    """
    yahoo_symbol = _normalize_symbol(symbol)
    ticker = yf.Ticker(yahoo_symbol)

    try:
        price = _positive_price(ticker.fast_info["last_price"])
    except Exception as exc:
        logger.debug("Yahoo fast_info unavailable for %s: %s", yahoo_symbol, exc)
        price = None

    if price is not None:
        return price

    history = ticker.history(
        period="5d",
        interval="1d",
        auto_adjust=False,
        actions=False,
    )
    price = _latest_close(history)
    if price is None:
        raise LookupError(f"Yahoo Finance returned no price for {yahoo_symbol}.")
    return price


def get_share_price(symbol: str) -> float:
    """Return a symbol's latest price, or ``0.0`` when Yahoo has no quote."""
    try:
        return get_share_price_yfinance(symbol)
    except Exception as exc:
        logger.warning("Could not fetch %s from Yahoo Finance: %s", symbol, exc)
        return 0.0


def get_share_prices(symbols: Iterable[str]) -> dict[str, float]:
    """Return valid latest prices keyed by normalized input symbol."""
    prices: dict[str, float] = {}
    seen: set[str] = set()
    for raw_symbol in symbols:
        symbol = str(raw_symbol).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        price = get_share_price(symbol)
        if price > 0:
            prices[symbol] = price
        else:
            logger.warning("No Yahoo Finance price available for %s", symbol)
    return prices
