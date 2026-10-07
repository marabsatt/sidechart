from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import uuid
from datetime import date, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from time import monotonic
from typing import Any, Dict, List, Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Load environment variables
load_dotenv(override=True)

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
for import_path in (ROOT_DIR, SRC_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

app = FastAPI(
    title="SideChart API",
    description="Backend API for SideChart AI-assisted market research, signals, rebalancing, and paper execution.",
    version="0.1.0",
)

# Configure CORS
local_origins = {
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
}
configured_origins = {
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "").split(",")
    if origin.strip()
}
origins = sorted(local_origins | configured_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Memory directory
MEMORY_DIR = ROOT_DIR / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

PERSONALITY = """
You are SideChart, an AI assistant for financial professionals. Be concise,
analytical, compliance-aware, and clear about uncertainty. You can discuss
market data, signals, draft allocations, and research context, but you do not
guarantee returns or present informational analysis as personalized investment
advice.
"""

IB_CONNECTION: Optional[Any] = None
IB_CONNECTION_DETAILS: dict[str, Any] = {}
IB_CONNECTION_LOCK = asyncio.Lock()
DEFAULT_IB_PORTS = list(
    dict.fromkeys(
        [
            int(os.getenv("IB_PORT", "7497")),
            7497,
            4002,
            7496,
            4001,
        ]
    )
)


def _get_openai_client() -> Any:
    try:
        from openai import OpenAI

        return OpenAI()
    except ModuleNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="The openai package is not installed for this backend environment.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"OpenAI client is not configured: {exc}",
        ) from exc


def _load_local_module(module_name: str, file_path: Path) -> Any:
    spec = spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from {file_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _records_from_dataframe(df: Any) -> list[dict[str, Any]]:
    import pandas as pd

    if df is None or getattr(df, "empty", True):
        return []

    serializable_df = df.copy()
    for column in serializable_df.columns:
        if pd.api.types.is_datetime64_any_dtype(serializable_df[column]):
            serializable_df[column] = serializable_df[column].dt.strftime(
                "%Y-%m-%dT%H:%M:%S"
            )

    serializable_df = serializable_df.where(pd.notnull(serializable_df), None)
    return [_make_json_safe(record) for record in serializable_df.to_dict(orient="records")]


def _dataframe_from_records(records: list[dict[str, Any]], required: set[str] | None = None):
    import pandas as pd

    df = pd.DataFrame(records)
    if required:
        missing = required.difference(df.columns)
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"Missing required columns: {sorted(missing)}",
            )
    return df


def _make_json_safe(value: Any) -> Any:
    try:
        import pandas as pd
    except ModuleNotFoundError:
        pd = None

    if pd is not None:
        if isinstance(value, pd.DataFrame):
            return _records_from_dataframe(value)
        if isinstance(value, pd.Series):
            return _make_json_safe(value.to_dict())
        if not isinstance(value, (dict, list, tuple, set)) and pd.isna(value):
            return None

    if isinstance(value, dict):
        return {str(key): _make_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_make_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        return {
            key: _make_json_safe(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return value


def _compact_pipeline_results(pipeline_results: dict[str, Any] | None) -> dict[str, Any]:
    if not pipeline_results:
        return {"status": "not_run"}

    compact = {
        "status": pipeline_results.get("status"),
        "bullish_tickers": pipeline_results.get("bullish_tickers", [])[:30],
        "bearish_tickers": pipeline_results.get("bearish_tickers", [])[:30],
        "top_performers": pipeline_results.get("top_performers", [])[:30],
        "candidate_tickers": pipeline_results.get("candidate_tickers", [])[:30],
        "allocation_tickers": pipeline_results.get("allocation_tickers", [])[:30],
        "signal_fallback": pipeline_results.get("signal_fallback"),
        "weights": pipeline_results.get("weights", [])[:30],
    }

    market_data = pipeline_results.get("market_data", [])
    signals_data = pipeline_results.get("signals_data", [])
    if isinstance(market_data, list):
        compact["market_data_sample"] = market_data[-30:]
        compact["market_data_rows"] = len(market_data)
    if isinstance(signals_data, list):
        compact["signals_data_sample"] = signals_data[-30:]
        compact["signals_data_rows"] = len(signals_data)

    return _make_json_safe(compact)


def _chat_completion_text(messages: list[dict[str, str]], temperature: float = 0.2) -> str:
    response = _get_openai_client().chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=messages,
        temperature=temperature,
    )
    return response.choices[0].message.content or ""


def _trade_to_record(trade: Any) -> dict[str, Any]:
    contract = getattr(trade, "contract", None)
    order = getattr(trade, "order", None)
    status = getattr(trade, "orderStatus", None)
    return {
        "symbol": getattr(contract, "symbol", None),
        "exchange": getattr(contract, "exchange", None),
        "currency": getattr(contract, "currency", None),
        "action": getattr(order, "action", None),
        "order_id": getattr(order, "orderId", None),
        "perm_id": getattr(order, "permId", None),
        "order_type": getattr(order, "orderType", None),
        "quantity": getattr(order, "totalQuantity", None),
        "tif": getattr(order, "tif", None),
        "status": getattr(status, "status", None),
        "filled": getattr(status, "filled", None),
        "remaining": getattr(status, "remaining", None),
        "avg_fill_price": getattr(status, "avgFillPrice", None),
    }


async def _await_order_acknowledgment(trade: Any, timeout: float = 8.0) -> None:
    deadline = monotonic() + timeout
    while getattr(trade.orderStatus, "status", "") in {"", "PendingSubmit"}:
        if monotonic() >= deadline:
            return
        await asyncio.sleep(0.2)

    if trade.orderStatus.status in {"Inactive", "Cancelled", "ApiCancelled"}:
        log = getattr(trade, "log", [])
        reason = getattr(log[-1], "message", "") if log else ""
        raise RuntimeError(f"IBKR rejected the order: {reason or trade.orderStatus.status}")


def _account_net_liquidation(ib: Any) -> float:
    account_values = ib.accountValues()
    net_liquidation = next(
        (
            value.value
            for value in account_values
            if value.tag == "NetLiquidation" and value.currency in {"USD", "BASE"}
        ),
        None,
    )
    if net_liquidation is None:
        raise ValueError("Could not determine NetLiquidation from IBKR account")

    account_value = float(net_liquidation)
    if account_value <= 0:
        raise ValueError("IBKR NetLiquidation must be greater than zero")
    return account_value


async def _latest_ib_price(ib: Any, ticker: str) -> float:
    from ib_insync import Stock

    contract = Stock(ticker, "SMART", "USD")
    qualified = await ib.qualifyContractsAsync(contract)
    if qualified:
        contract = qualified[0]

    ib.reqMarketDataType(3)
    market_ticker = (await ib.reqTickersAsync(contract))[0]
    price = market_ticker.marketPrice()
    if price is None or not math.isfinite(price) or price <= 0:
        price_candidates = [
            market_ticker.last,
            market_ticker.close,
            market_ticker.bid,
            market_ticker.ask,
        ]
        valid_prices = [
            float(value) for value in price_candidates
            if value is not None and math.isfinite(value) and value > 0
        ]
        if market_ticker.bid and market_ticker.ask and market_ticker.bid > 0 and market_ticker.ask > 0:
            valid_prices.insert(0, (float(market_ticker.bid) + float(market_ticker.ask)) / 2)
        if not valid_prices:
            raise ValueError(f"Could not determine a market price for {ticker}")
        price = valid_prices[0]

    return float(price)


async def _weighted_order_quantity(ib: Any, ticker: str, target_weight: float) -> dict[str, float]:
    if target_weight <= 0:
        raise ValueError("target_weight must be greater than zero")

    try:
        account_value = _account_net_liquidation(ib)
    except ValueError:
        # The persistent IBKR connection normally has account updates already.
        # Request a summary only when those updates have not arrived yet.
        await ib.accountSummaryAsync()
        account_value = _account_net_liquidation(ib)
    market_price = await _latest_ib_price(ib, ticker)
    target_notional = account_value * target_weight
    quantity = math.floor(target_notional / market_price)
    if quantity <= 0:
        raise ValueError(
            f"Target notional ${target_notional:,.2f} is below one share of {ticker} at ${market_price:,.2f}"
        )

    return {
        "account_value": account_value,
        "market_price": market_price,
        "target_notional": target_notional,
        "quantity": float(quantity),
    }


def _position_to_record(position: Any) -> dict[str, Any]:
    contract = getattr(position, "contract", None)
    return {
        "account": getattr(position, "account", None),
        "symbol": getattr(contract, "symbol", None),
        "exchange": getattr(contract, "exchange", None),
        "currency": getattr(contract, "currency", None),
        "position": getattr(position, "position", None),
        "avg_cost": getattr(position, "avgCost", None),
    }


def _connect_ib(host: str, port: int, client_id: int, timeout: float = 4.0):
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    from ib_insync import IB

    ib = IB()
    ib.connect(host, port, clientId=client_id, timeout=timeout)
    return ib


def _ib_connection_status() -> dict[str, Any]:
    connected = bool(IB_CONNECTION and IB_CONNECTION.isConnected())
    return {
        "connected": connected,
        "host": IB_CONNECTION_DETAILS.get("host"),
        "port": IB_CONNECTION_DETAILS.get("port"),
        "client_id": IB_CONNECTION_DETAILS.get("client_id"),
        "connected_at": IB_CONNECTION_DETAILS.get("connected_at"),
        "mode": IB_CONNECTION_DETAILS.get("mode"),
    }


async def _connect_shared_ib(
    host: str,
    port: int,
    client_id: int,
    timeout: float = 4.0,
) -> dict[str, Any]:
    global IB_CONNECTION
    global IB_CONNECTION_DETAILS

    async with IB_CONNECTION_LOCK:
        if IB_CONNECTION and IB_CONNECTION.isConnected():
            same_target = (
                IB_CONNECTION_DETAILS.get("host") == host
                and IB_CONNECTION_DETAILS.get("port") == port
                and IB_CONNECTION_DETAILS.get("client_id") == client_id
            )
            if same_target:
                return _ib_connection_status()
            IB_CONNECTION.disconnect()
        ib = None
        try:
            asyncio.set_event_loop(asyncio.get_running_loop())
            from ib_insync import IB

            ib = IB()
            await ib.connectAsync(host, port, clientId=client_id, timeout=timeout)
        except Exception:
            if ib is not None and ib.isConnected():
                ib.disconnect()
            raise

        IB_CONNECTION = ib
        IB_CONNECTION_DETAILS = {
            "host": host,
            "port": port,
            "client_id": client_id,
            "connected_at": datetime.utcnow().isoformat(),
            "mode": "IBKR Gateway" if port in {4001, 4002} else "Trader Workstation",
        }
        return _ib_connection_status()


async def _get_order_ib(host: str, port: int, client_id: int) -> Any:
    if IB_CONNECTION and IB_CONNECTION.isConnected():
        return IB_CONNECTION
    await _connect_shared_ib(host, port, client_id)
    return IB_CONNECTION


def _normalize_tickers(tickers: list[str] | None) -> list[str]:
    if not tickers:
        return []
    return sorted({ticker.strip().upper() for ticker in tickers if ticker.strip()})

# Memory functions
def load_conversation(session_id: str) -> List[Dict]:
    """Load conversation history from file."""
    file_path = MEMORY_DIR / f"{session_id}.json"
    if file_path.exists():
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_conversation(session_id: str, messages: List[Dict]) -> None:
    """Save conversation history to file."""
    file_path = MEMORY_DIR / f"{session_id}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(messages, f, indent=2, ensure_ascii=False)


# Request/Response models
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    session_id: str


class MarketDataRequest(BaseModel):
    tickers: Optional[list[str]] = None
    period: str = "3y"
    interval: str = "1mo"
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class IndicatorRequest(BaseModel):
    values: list[float]
    period: int = Field(default=14, gt=0)


class MacdRequest(BaseModel):
    values: list[float]
    fast_period: int = Field(default=12, gt=0)
    slow_period: int = Field(default=26, gt=0)
    signal_period: int = Field(default=9, gt=0)


class SignalsRequest(BaseModel):
    market_data: list[dict[str, Any]]


class PipelineRequest(BaseModel):
    tickers: list[str]
    lookback_months: int = Field(default=3, gt=0)
    num_signals: int = Field(default=20, gt=0)


class WeightRecord(BaseModel):
    ticker: str
    weights: float = Field(ge=0)


class RebalanceProposalRequest(BaseModel):
    target_weights: list[WeightRecord]
    rationale: str = "Draft allocation generated through the SideChart API."
    status: str = "draft"
    source_signals: dict[str, Any] = Field(default_factory=dict)
    source_research: str = ""
    actions: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class BrokerConnectionRequest(BaseModel):
    host: str = os.getenv("IB_HOST", "127.0.0.1")
    port: int = int(os.getenv("IB_PORT", "7497"))
    client_id: int = Field(default=int(os.getenv("IB_CLIENT_ID", "17")), gt=0)


class BrokerConnectRequest(BrokerConnectionRequest):
    ports: Optional[list[int]] = None
    timeout: float = Field(default=30.0, gt=0)
    connect_timeout: float = Field(default=4.0, gt=0)
    poll_interval: float = Field(default=1.0, gt=0)


class OrderRequest(BrokerConnectionRequest):
    ticker: str
    quantity: Optional[float] = Field(default=None, gt=0)
    target_weight: Optional[float] = Field(default=None, gt=0)
    dry_run: bool = True


class ExecutionRequest(BrokerConnectionRequest):
    target_weights: list[WeightRecord]
    account_value: Optional[float] = Field(default=None, gt=0)
    sell_timeout: float = Field(default=300.0, gt=0)
    dry_run: bool = True


class SupervisorContextRequest(BaseModel):
    tickers: Optional[list[str]] = None
    sellside_research: Optional[str] = None
    pipeline_results: Optional[dict[str, Any]] = None
    current_positions: Optional[list[dict[str, Any]]] = None
    lookback_months: int = Field(default=3, gt=0)
    num_signals: int = Field(default=20, gt=0)


class ResearchAgentRunRequest(BaseModel):
    tickers: Optional[list[str]] = None
    source_context: Optional[str] = None
    pipeline_results: Optional[dict[str, Any]] = None
    lookback_months: int = Field(default=3, gt=0)
    num_signals: int = Field(default=20, gt=0)


class SupervisorAgentRunRequest(SupervisorContextRequest):
    pass


class AgentIngestRequest(BaseModel):
    agent: Literal["research", "supervisor"]
    topic: str
    analysis: str


@app.get("/")
async def root():
    return {
        "message": "SideChart AI Assisted Trading",
        "services": [
            "chat",
            "market-data",
            "signals",
            "pipeline",
            "rebalance",
            "orders",
            "execution",
            "agents",
        ],
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.get("/broker/ibkr/status")
async def get_ibkr_connection_status():
    return _ib_connection_status()


@app.post("/broker/ibkr/connect")
async def connect_ibkr(request: BrokerConnectRequest):
    deadline = monotonic() + request.timeout
    errors: list[str] = []
    ports = list(dict.fromkeys(request.ports or DEFAULT_IB_PORTS))

    while True:
        for port in ports:
            try:
                status = await _connect_shared_ib(
                    request.host,
                    port,
                    request.client_id,
                    request.connect_timeout,
                )
                return {
                    **status,
                    "message": f"Connected to {status['mode']} on {request.host}:{port}.",
                }
            except Exception as exc:
                errors.append(f"{request.host}:{port} - {exc}")

        if monotonic() >= deadline:
            raise HTTPException(
                status_code=504,
                detail=(
                    "Timed out waiting for IBKR Trader Workstation or Gateway. "
                    f"Attempts: {'; '.join(errors[-len(ports):])}"
                ),
            )

        await asyncio.sleep(min(request.poll_interval, max(0.1, deadline - monotonic())))


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        session_id = request.session_id or str(uuid.uuid4())
        conversation = load_conversation(session_id)

        messages = [{"role": "system", "content": PERSONALITY}]
        messages.extend(conversation)
        messages.append({"role": "user", "content": request.message})

        response = _get_openai_client().chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=messages,
        )

        assistant_response = response.choices[0].message.content or ""
        conversation.append({"role": "user", "content": request.message})
        conversation.append({"role": "assistant", "content": assistant_response})
        save_conversation(session_id, conversation)

        return ChatResponse(response=assistant_response, session_id=session_id)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/sessions")
async def list_sessions():
    """List all conversation sessions."""
    sessions = []
    for file_path in MEMORY_DIR.glob("*.json"):
        session_id = file_path.stem
        with open(file_path, "r", encoding="utf-8") as f:
            conversation = json.load(f)
            sessions.append(
                {
                    "session_id": session_id,
                    "message_count": len(conversation),
                    "last_message": conversation[-1]["content"] if conversation else None,
                }
            )
    return {"sessions": sessions}


@app.get("/market-data/tickers/sp500")
async def get_sp500_tickers():
    try:
        from contracts.dev.market_data import get_sp500_tickers

        return {"tickers": get_sp500_tickers()}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/market-data/tickers/nasdaq100")
async def get_nasdaq_100_tickers():
    try:
        from contracts.dev.market_data import get_nasdaq_100_tickers

        return {"tickers": get_nasdaq_100_tickers()}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/market-data")
async def get_market_data(request: MarketDataRequest):
    """Fetch dev market data using the contract in src/contracts/dev."""
    try:
        from contracts.dev.market_data import get_market_data

        tickers = _normalize_tickers(request.tickers) or None
        result = get_market_data(
            tickers,
            start_date=request.start_date,
            end_date=request.end_date,
            period=request.period,
            interval=request.interval,
        )
        if isinstance(result, tuple):
            market_data, failed_tickers = result
        else:
            market_data = result
            failed_tickers = getattr(market_data, "attrs", {}).get("failed_tickers", [])

        return {
            "tickers": tickers,
            "period": request.period,
            "interval": request.interval,
            "data": _records_from_dataframe(market_data),
            "failed_tickers": _make_json_safe(failed_tickers),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/market-data/prod/status")
async def get_prod_market_status():
    """Optional production market status endpoint backed by the prod contract."""
    try:
        from contracts.prod.market_data import is_market_open

        return {"market_status": is_market_open()}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/signals/rsi")
async def calculate_rsi(request: IndicatorRequest):
    try:
        import pandas as pd
        from contracts.signals import rsi

        values = pd.Series(request.values)
        return {"values": _make_json_safe(rsi(values, request.period).tolist())}
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/signals/ema")
async def calculate_ema(request: IndicatorRequest):
    try:
        import pandas as pd
        from contracts.signals import ema

        values = pd.Series(request.values)
        return {"values": _make_json_safe(ema(values, request.period).tolist())}
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/signals/macd")
async def calculate_macd(request: MacdRequest):
    try:
        import pandas as pd
        from contracts.signals import macd

        values = pd.Series(request.values)
        macd_line, signal_line, histogram = macd(
            values,
            fast_period=request.fast_period,
            slow_period=request.slow_period,
            signal_period=request.signal_period,
        )
        return {
            "macd": _make_json_safe(macd_line.tolist()),
            "signal": _make_json_safe(signal_line.tolist()),
            "histogram": _make_json_safe(histogram.tolist()),
        }
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/signals/generate")
async def generate_signals(request: SignalsRequest):
    try:
        from contracts.signals import signal_generator

        market_df = _dataframe_from_records(
            request.market_data,
            required={"ticker", "date", "close", "volume"},
        )
        bullish_tickers, bearish_tickers, signals_df = signal_generator(market_df)
        return {
            "bullish_tickers": bullish_tickers,
            "bearish_tickers": bearish_tickers,
            "signals_data": _records_from_dataframe(signals_df),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/pipeline/dev/analyze")
async def run_dev_analysis_pipeline(request: PipelineRequest):
    try:
        from contracts.dev.pipeline import run_analysis_pipeline

        result = await asyncio.to_thread(
            run_analysis_pipeline,
            _normalize_tickers(request.tickers),
            request.lookback_months,
            request.num_signals,
        )
        return _make_json_safe(result)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/rebalance/proposal")
async def create_rebalance_proposal(request: RebalanceProposalRequest):
    try:
        import pandas as pd
        from contracts.rebalance import RebalanceProposal

        proposal = RebalanceProposal(
            target_weights=pd.DataFrame(
                [_model_to_dict(weight) for weight in request.target_weights]
            ),
            rationale=request.rationale,
            status=request.status,
            source_signals=request.source_signals,
            source_research=request.source_research,
            actions=request.actions,
            assumptions=request.assumptions,
            risks=request.risks,
        )
        return proposal.to_dict()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/portfolio/holdings/dev")
async def get_dev_current_holdings():
    try:
        from contracts.dev.current_holdings import get_current_holdings

        positions = get_current_holdings()
        return {"holdings": [_position_to_record(position) for position in positions]}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/portfolio/holdings")
async def get_current_holdings(
    host: str = os.getenv("IB_HOST", "127.0.0.1"),
    port: int = int(os.getenv("IB_PORT", "7497")),
    client_id: int = int(os.getenv("IB_CLIENT_ID", "17")),
):
    """Return current positions from the shared asynchronous IBKR session."""
    try:
        ib = await _get_order_ib(host, port, client_id)
        async with IB_CONNECTION_LOCK:
            positions = ib.positions()
        return {
            "connected": bool(ib.isConnected()),
            "holdings": [_position_to_record(position) for position in positions],
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/orders/buy")
async def buy_order(request: OrderRequest):
    if request.quantity is None and request.target_weight is None:
        raise HTTPException(
            status_code=422,
            detail="quantity or target_weight is required for buy orders",
        )
    if request.dry_run:
        preview = {
            "dry_run": True,
            "order": {
                "action": "BUY",
                "ticker": request.ticker.upper(),
                "quantity": request.quantity,
                "target_weight": request.target_weight,
                "order_type": "MKT",
                "tif": "GTC",
            },
        }
        if request.target_weight is not None and IB_CONNECTION and IB_CONNECTION.isConnected():
            try:
                async with IB_CONNECTION_LOCK:
                    sizing = await _weighted_order_quantity(
                        IB_CONNECTION, request.ticker.upper(), request.target_weight
                    )
                preview["order"]["quantity"] = sizing["quantity"]
                preview["sizing"] = sizing
            except Exception as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        return preview

    try:
        from contracts.orders import buy_stock
        from ib_insync import Stock

        ib = await _get_order_ib(
            request.host,
            request.port,
            request.client_id,
        )
        async with IB_CONNECTION_LOCK:
            sizing = None
            quantity = request.quantity
            if quantity is None:
                sizing = await _weighted_order_quantity(
                    ib,
                    request.ticker.upper(),
                    float(request.target_weight or 0),
                )
                quantity = sizing["quantity"]
            contract = Stock(request.ticker.upper(), "SMART", "USD")
            qualified_contracts = await ib.qualifyContractsAsync(contract)
            if not qualified_contracts:
                raise ValueError(f"IBKR could not qualify contract {request.ticker.upper()}")
            trade = buy_stock(
                ib,
                request.ticker.upper(),
                quantity,
                contract=qualified_contracts[0],
            )
            await _await_order_acknowledgment(trade)

        response = {"dry_run": False, "trade": _trade_to_record(trade)}
        if sizing is not None:
            response["sizing"] = sizing
        return response
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/orders/sell")
async def sell_order(request: OrderRequest):
    if request.dry_run:
        return {
            "dry_run": True,
            "order": {
                "action": "SELL",
                "ticker": request.ticker.upper(),
                "quantity": request.quantity,
                "order_type": "MKT",
                "tif": "GTC",
            },
        }

    try:
        from contracts.orders import sell_stock
        from ib_insync import Stock

        ib = await _get_order_ib(
            request.host,
            request.port,
            request.client_id,
        )
        async with IB_CONNECTION_LOCK:
            ticker = request.ticker.upper()
            position = next(
                (
                    current_position
                    for current_position in ib.positions()
                    if getattr(getattr(current_position, "contract", None), "symbol", "") == ticker
                ),
                None,
            )
            available_quantity = float(getattr(position, "position", 0) or 0)
            if available_quantity <= 0:
                raise ValueError(f"No long position found for {ticker}")
            if request.quantity is not None and request.quantity > available_quantity:
                raise ValueError(
                    f"Cannot sell {request.quantity} shares of {ticker}; only {available_quantity} are held"
                )

            contract = Stock(ticker, "SMART", "USD")
            qualified_contracts = await ib.qualifyContractsAsync(contract)
            if not qualified_contracts:
                raise ValueError(f"IBKR could not qualify contract {ticker}")
            trade = sell_stock(
                ib,
                ticker,
                request.quantity,
                contract=qualified_contracts[0],
            )
            await _await_order_acknowledgment(trade)
        return {"dry_run": False, "trade": _trade_to_record(trade)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/execution/rebalance")
async def execute_rebalance_endpoint(request: ExecutionRequest):
    import pandas as pd

    target_weights = pd.DataFrame(
        [_model_to_dict(weight) for weight in request.target_weights]
    )
    if request.dry_run:
        return {
            "dry_run": True,
            "target_weights": _records_from_dataframe(target_weights),
            "message": "Dry run only. Set dry_run=false to submit paper orders through IBKR.",
        }

    try:
        from contracts.execution import execute_rebalance

        def run_rebalance():
            client_id = request.client_id + (1 if IB_CONNECTION and IB_CONNECTION.isConnected() else 0)
            ib = _connect_ib(request.host, request.port, client_id)
            try:
                return execute_rebalance(
                    ib=ib,
                    target_weights=target_weights,
                    account_value=request.account_value,
                    sell_timeout=request.sell_timeout,
                )
            finally:
                if ib.isConnected():
                    ib.disconnect()

        trades = await asyncio.to_thread(run_rebalance)
        return {
            "dry_run": False,
            "execution_status": "submitted",
            "trades": [_trade_to_record(trade) for trade in trades],
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/agents/research/prompt")
async def get_research_agent_prompt():
    try:
        research_context = _load_local_module(
            "sidechart_research_context",
            SRC_DIR / "agents" / "research" / "context.py",
        )

        prompt_parts = []
        if hasattr(research_context, "sellside_agent_instructions"):
            prompt_parts.append(research_context.sellside_agent_instructions().strip())
        prompt_parts.append(research_context.DEFAULT_RESEARCH_PROMPT.strip())
        return {"prompt": "\n\n".join(prompt_parts)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/agents/research/run")
async def run_research_agent(request: ResearchAgentRunRequest):
    try:
        research_context = _load_local_module(
            "sidechart_research_context",
            SRC_DIR / "agents" / "research" / "context.py",
        )

        tickers = _normalize_tickers(request.tickers)
        compact_pipeline = _compact_pipeline_results(request.pipeline_results)
        user_context = request.source_context or "No additional sell-side notes supplied."
        prompt = f"""
Generate an institutional sell-side research output for the SideChart workflow.

Ticker universe:
{tickers or "Unavailable"}

User supplied research context:
{user_context}

SideChart pipeline context:
{json.dumps(compact_pipeline, indent=2)}

Requirements:
- Cover every ticker in the supplied ticker universe. Do not select only one
  ticker unless the universe contains one ticker.
- Include every ticker in a coverage matrix and in ticker-by-ticker notes.
- Use the target weights, signal classifications, latest indicators, and
  performance context from the SideChart pipeline where available.
- Separate observed data from estimates.
- State unavailable valuation, filing, or news data explicitly.
- Keep the output professional, concise, and suitable for a buy-side portfolio
  manager or investment committee.
- Include an informational-analysis disclaimer.

Output format:
Portfolio Research Note
1. Executive Summary
2. Coverage Matrix
3. Ticker-by-Ticker Notes
4. Portfolio Implications
5. Compliance Note
"""

        system_prompt_parts = []
        if hasattr(research_context, "sellside_agent_instructions"):
            system_prompt_parts.append(research_context.sellside_agent_instructions().strip())
        system_prompt_parts.append(research_context.DEFAULT_RESEARCH_PROMPT.strip())

        output = _chat_completion_text(
            [
                {
                    "role": "system",
                    "content": "\n\n".join(system_prompt_parts),
                },
                {"role": "user", "content": prompt.strip()},
            ],
            temperature=0.2,
        )
        return {"output": output}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/agents/supervisor/context")
async def get_supervisor_agent_context(request: SupervisorContextRequest):
    try:
        supervisor_context = _load_local_module(
            "sidechart_supervisor_context",
            SRC_DIR / "agents" / "supervisor" / "context.py",
        )

        context = supervisor_context.supervisor_agent(
            tickers=_normalize_tickers(request.tickers),
            sellside_research=request.sellside_research,
            pipeline_results=request.pipeline_results,
            current_positions=request.current_positions,
            lookback_months=request.lookback_months,
            num_signals=request.num_signals,
        )
        return {"context": context}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/agents/supervisor/run")
async def run_supervisor_agent(request: SupervisorAgentRunRequest):
    try:
        supervisor_context = _load_local_module(
            "sidechart_supervisor_context",
            SRC_DIR / "agents" / "supervisor" / "context.py",
        )

        context = supervisor_context.supervisor_agent(
            tickers=_normalize_tickers(request.tickers),
            sellside_research=request.sellside_research,
            pipeline_results=request.pipeline_results,
            current_positions=request.current_positions,
            lookback_months=request.lookback_months,
            num_signals=request.num_signals,
        )
        output = _chat_completion_text(
            [
                {
                    "role": "system",
                    "content": (
                        "You are the SideChart supervisor agent. Produce a clean, finance-professional "
                        "rebalance memo with exactly two top-level sections: RebalanceProposal and "
                        "Rationale. Use markdown tables for ticker/action details. Do not execute trades."
                    ),
                },
                {"role": "user", "content": context},
            ],
            temperature=0.1,
        )
        return {"context": context, "output": output}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/agents/ingest")
async def ingest_agent_document(request: AgentIngestRequest):
    try:
        if request.agent == "research":
            agent_tools = _load_local_module(
                "sidechart_research_tools",
                SRC_DIR / "agents" / "research" / "tools.py",
            )
        else:
            agent_tools = _load_local_module(
                "sidechart_supervisor_tools",
                SRC_DIR / "agents" / "supervisor" / "tools.py",
            )

        return agent_tools.ingest_financial_document(request.topic, request.analysis)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
