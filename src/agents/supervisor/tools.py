import os
from typing import Any, Dict, Iterable
from datetime import datetime, timezone

try:
    import httpx
except ModuleNotFoundError:
    httpx = None

try:
    from agents import function_tool
except (ImportError, ModuleNotFoundError):
    def function_tool(func):
        return func

try:
    from tenacity import retry, stop_after_attempt, wait_exponential
except ModuleNotFoundError:
    def retry(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    def stop_after_attempt(*args, **kwargs):
        return None

    def wait_exponential(*args, **kwargs):
        return None

# Configuration from environment
SUPERVISOR_API_ENDPOINT = os.getenv("SUPERVISOR_API_ENDPOINT")
SUPERVISOR_API_KEY = os.getenv("SUPERVISOR_API_KEY")


def _get_pandas():
    import pandas as pd

    return pd


def _records_from_dataframe(df: Any) -> list[Dict[str, Any]]:
    """Convert a DataFrame into JSON-safe row records."""
    pd = _get_pandas()
    if df.empty:
        return []
    serializable_df = df.copy()
    for column in serializable_df.columns:
        if pd.api.types.is_datetime64_any_dtype(serializable_df[column]):
            serializable_df[column] = serializable_df[column].dt.strftime(
                "%Y-%m-%dT%H:%M:%S"
            )
    return serializable_df.where(pd.notnull(serializable_df), None).to_dict(
        orient="records"
    )


def _position_to_record(position: Any) -> Dict[str, Any]:
    """Convert an ib_insync position-like object into a JSON-safe dictionary."""
    contract = getattr(position, "contract", None)
    return {
        "account": getattr(position, "account", None),
        "symbol": getattr(contract, "symbol", None),
        "exchange": getattr(contract, "exchange", None),
        "currency": getattr(contract, "currency", None),
        "position": getattr(position, "position", None),
        "avg_cost": getattr(position, "avgCost", None),
    }


def _normalize_tickers(tickers: Iterable[str]) -> list[str]:
    return sorted({ticker.strip().upper() for ticker in tickers if ticker.strip()})


def _ingest(document: Dict[str, Any]) -> Dict[str, Any]:
    """Internal function to make the actual API call."""
    if httpx is None:
        raise RuntimeError("httpx is required to ingest supervisor documents")

    with httpx.Client() as client:
        response = client.post(
            SUPERVISOR_API_ENDPOINT,
            json=document,
            headers={"x-api-key": SUPERVISOR_API_KEY},
            timeout=30.0
        )
        response.raise_for_status()
        return response.json()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10)
)
def ingest_with_retries(document: Dict[str, Any]) -> Dict[str, Any]:
    """Ingest with retry logic for SageMaker cold starts."""
    return _ingest(document)


@function_tool
def ingest_financial_document(topic: str, analysis: str) -> Dict[str, Any]:
    """
    Ingest a financial document into the SUPERVISOR knowledge base.
    
    Args:
        topic: The topic or subject of the analysis (e.g., "AAPL Stock Analysis", "Company's Filings")
        analysis: Detailed analysis or advice with specific data and insights
    
    Returns:
        Dictionary with success status and document ID
    """
    if not SUPERVISOR_API_ENDPOINT or not SUPERVISOR_API_KEY:
        return {
            "success": False,
            "error": "SUPERVISOR API not configured. Running in local mode."
        }
    
    document = {
        "text": analysis,
        "metadata": {
            "topic": topic,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    }
    
    try:
        result = ingest_with_retries(document)
        return {
            "success": True,
            "document_id": result.get("document_id"),  # Changed from documentId
            "message": f"Successfully ingested analysis for {topic}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@function_tool
def generate_trading_signals(market_data: list[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Call contracts.signals.signal_generator for supervisor signal synthesis.

    Args:
        market_data: OHLCV records with ticker, date, close, and volume columns

    Returns:
        Dictionary containing bullish tickers, bearish tickers, and indicator rows
    """
    if not market_data:
        return {
            "success": False,
            "error": "market_data is required",
            "bullish_tickers": [],
            "bearish_tickers": [],
            "signals_data": [],
        }

    try:
        from contracts.signals import signal_generator

        pd = _get_pandas()
        market_df = pd.DataFrame(market_data)
        bullish_tickers, bearish_tickers, signals_df = signal_generator(market_df)
        return {
            "success": True,
            "bullish_tickers": bullish_tickers,
            "bearish_tickers": bearish_tickers,
            "signals_data": _records_from_dataframe(signals_df),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "bullish_tickers": [],
            "bearish_tickers": [],
            "signals_data": [],
        }


@function_tool
def optimize_dev_portfolio_weights(
    tickers: list[str],
    lookback_days: int = 30,
) -> Dict[str, Any]:
    """
    Call contracts.dev.risk.port_opt to create draft target allocation weights.

    Args:
        tickers: Ticker symbols to optimize
        lookback_days: Historical lookback window used by the optimizer

    Returns:
        Dictionary containing target weight records
    """
    normalized_tickers = _normalize_tickers(tickers)
    if not normalized_tickers:
        return {
            "success": False,
            "error": "At least one ticker is required",
            "weights": [],
        }

    try:
        from contracts.dev.risk import port_opt

        weights_df = port_opt(normalized_tickers, lookback_days=lookback_days)
        return {
            "success": True,
            "tickers": normalized_tickers,
            "lookback_days": lookback_days,
            "weights": _records_from_dataframe(weights_df),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "tickers": normalized_tickers,
            "lookback_days": lookback_days,
            "weights": [],
        }


@function_tool
def get_dev_current_holdings() -> Dict[str, Any]:
    """
    Call contracts.dev.current_holdings.get_current_holdings for IBKR paper holdings.

    Returns:
        Dictionary containing current position records
    """
    try:
        from contracts.dev.current_holdings import get_current_holdings

        positions = get_current_holdings()
        return {
            "success": True,
            "holdings": [_position_to_record(position) for position in positions],
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "holdings": [],
        }


@function_tool
def use_research_agent_output(
    topic: str,
    research_output: str,
    source_agent: str = "sellside_agent",
) -> Dict[str, Any]:
    """
    Structure the completed research agent output for supervisor synthesis.

    Args:
        topic: Research topic or ticker covered by the research agent
        research_output: Final output from the research agent
        source_agent: Name of the upstream research agent

    Returns:
        Dictionary containing research context for the supervisor
    """
    if not research_output.strip():
        return {
            "success": False,
            "error": "research_output is required",
            "research": None,
        }

    return {
        "success": True,
        "research": {
            "topic": topic,
            "source_agent": source_agent,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "output": research_output,
        },
    }


SUPERVISOR_TOOLS = [
    ingest_financial_document,
    generate_trading_signals,
    optimize_dev_portfolio_weights,
    get_dev_current_holdings,
    use_research_agent_output,
]
