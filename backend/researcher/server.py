"""SideChart researcher service.

The service keeps the AWS researcher workflow (Bedrock, Playwright MCP, and
SageMaker/S3 ingestion) and exposes the same application routes as the local
FastAPI service. The local router is included rather than copied so request
models and broker behavior stay in sync between environments.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field


load_dotenv(override=True)


def _repository_root() -> Path:
    """Resolve the repository root from source and from the container image."""
    current_file = Path(__file__).resolve()
    candidates = [
        current_file.parent,
        current_file.parent.parent,
        current_file.parent.parent.parent,
    ]
    for candidate in candidates:
        if (candidate / "src").is_dir() and (candidate / "backend").is_dir():
            return candidate
    return current_file.parent


REPOSITORY_ROOT = _repository_root()
SRC_DIR = REPOSITORY_ROOT / "src"
for import_path in (REPOSITORY_ROOT, SRC_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

# Lambda's image filesystem is read-only outside /tmp. The local router uses
# this directory for chat sessions, so redirect it only for Lambda execution.
if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
    os.environ.setdefault("SIDECHART_MEMORY_DIR", "/tmp/sidechart-memory")


logging.basicConfig(level=logging.INFO)
logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)


try:
    from . import context as researcher_context
except ImportError:
    import context as researcher_context


DEFAULT_RESEARCH_PROMPT = researcher_context.DEFAULT_RESEARCH_PROMPT
MCP_LOGGING_ENABLED = os.getenv("MCP_LOGGING") == "True"


app = FastAPI(
    title="SideChart Researcher Service",
    description=(
        "AWS researcher service with the same market, signal, portfolio, "
        "broker, and agent API contracts as the local SideChart backend."
    ),
    version="0.1.0",
)

configured_origins = {
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "").split(",")
    if origin.strip()
}
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(
        configured_origins
        | {
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
        }
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _trim_for_log(value: Any, max_length: int = 1500) -> str:
    text = str(value)
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}... [trimmed {len(text) - max_length} chars]"


try:
    from agents import Agent, RunHooks, Runner, trace
    from agents.extensions.models.litellm_model import LitellmModel
except ModuleNotFoundError:
    Agent = None
    Runner = None
    trace = None
    LitellmModel = None

    class RunHooks:  # type: ignore[no-redef]
        """Import-safe fallback; agent requests report the missing dependency."""


class ResearchLoggingHooks(RunHooks):
    async def on_tool_start(self, context, agent, tool) -> None:
        if MCP_LOGGING_ENABLED:
            logger.info(
                "[tool:start] name=%s type=%s repr=%s",
                getattr(tool, "name", type(tool).__name__),
                type(tool).__name__,
                _trim_for_log(repr(tool), max_length=500),
            )

    async def on_tool_end(self, context, agent, tool, result) -> None:
        if MCP_LOGGING_ENABLED:
            logger.info(
                "[tool:end] name=%s result=%s",
                getattr(tool, "name", type(tool).__name__),
                _trim_for_log(result),
            )


def _load_module(module_name: str, file_path: Path) -> Any:
    if not file_path.is_file():
        raise ImportError(f"Could not find module at {file_path}")
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _agent_instructions(tickers: list[str] | None = None) -> str:
    """Support both the AWS context helper and the local context helper."""
    get_instructions = getattr(researcher_context, "get_agent_instructions", None)
    if callable(get_instructions):
        return get_instructions()

    sellside_instructions = getattr(
        researcher_context, "sellside_agent_instructions", None
    )
    if callable(sellside_instructions):
        # The pipeline snapshot is already supplied in the compatible agent
        # prompt. Avoid rerunning a market-data pipeline while constructing
        # the system instructions.
        return sellside_instructions()
    return DEFAULT_RESEARCH_PROMPT


def _load_agent_runtime() -> tuple[Any, Any, Any, Any, Any, Any]:
    if any(value is None for value in (Agent, Runner, trace, LitellmModel)):
        raise RuntimeError(
            "The AWS researcher dependencies are not installed. "
            "Install the project with `uv sync` so openai-agents and litellm are available."
        )

    try:
        from .mcp_servers import create_playwright_mcp_server
        from .tools import ingest_financial_document
    except ImportError:
        from mcp_servers import create_playwright_mcp_server
        from tools import ingest_financial_document

    return (
        Agent,
        Runner,
        trace,
        LitellmModel,
        create_playwright_mcp_server,
        ingest_financial_document,
    )


async def run_research_agent(
    topic: str | None = None,
    *,
    instructions: str | None = None,
    tickers: list[str] | None = None,
) -> str:
    """Run the Bedrock researcher used by AWS and local-compatible routes."""
    (
        agent_class,
        runner,
        trace_context,
        model_class,
        create_mcp_server,
        ingest_tool,
    ) = _load_agent_runtime()

    query = (
        f"Research this investment topic: {topic}"
        if topic
        else DEFAULT_RESEARCH_PROMPT
    )
    if MCP_LOGGING_ENABLED:
        logger.info(
            "Starting research agent topic_provided=%s query_preview=%s",
            bool(topic),
            _trim_for_log(query, max_length=500),
        )

    region = os.environ.get("BEDROCK_REGION", "us-west-2")
    os.environ["AWS_REGION_NAME"] = region
    os.environ["AWS_REGION"] = region
    os.environ["AWS_DEFAULT_REGION"] = region
    model_name = os.environ.get(
        "RESEARCHER_MODEL", "bedrock/converse/openai.gpt-oss-120b-1:0"
    )
    model = model_class(model=model_name)
    agent_instructions = instructions or _agent_instructions(tickers=tickers)

    if MCP_LOGGING_ENABLED:
        logger.info("Research agent runtime model=%s aws_region=%s", model_name, region)

    with trace_context("Researcher"):
        async with create_mcp_server(timeout_seconds=120) as playwright_mcp:
            agent = agent_class(
                name="Sidechart Sell-side Researcher",
                instructions=agent_instructions,
                model=model,
                tools=[ingest_tool],
                mcp_servers=[playwright_mcp],
            )
            result = await runner.run(
                agent,
                input=query,
                max_turns=30,
                hooks=ResearchLoggingHooks() if MCP_LOGGING_ENABLED else None,
            )

    return result.final_output


class ResearchRequest(BaseModel):
    topic: Optional[str] = None


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
    agent: str
    topic: str
    analysis: str


def _normalize_tickers(tickers: list[str] | None) -> list[str]:
    if not tickers:
        return []
    return sorted({ticker.strip().upper() for ticker in tickers if ticker.strip()})


def _compact_pipeline_results(
    pipeline_results: dict[str, Any] | None,
) -> dict[str, Any]:
    if not pipeline_results:
        return {"status": "not_run"}
    keys = (
        "status",
        "bullish_tickers",
        "bearish_tickers",
        "top_performers",
        "candidate_tickers",
        "allocation_tickers",
        "weights",
        "signal_fallback",
    )
    compact = {key: pipeline_results.get(key) for key in keys}
    for key in ("market_data", "signals_data"):
        value = pipeline_results.get(key)
        if isinstance(value, list):
            compact[f"{key}_sample"] = value[-30:]
            compact[f"{key}_rows"] = len(value)
    return compact


def _supervisor_context(request: SupervisorContextRequest) -> str:
    context_module = _load_module(
        "sidechart_aws_supervisor_context",
        SRC_DIR / "agents" / "supervisor" / "context.py",
    )
    return context_module.supervisor_agent(
        tickers=_normalize_tickers(request.tickers),
        sellside_research=request.sellside_research,
        pipeline_results=request.pipeline_results,
        current_positions=request.current_positions,
        lookback_months=request.lookback_months,
        num_signals=request.num_signals,
    )


def _ingest_directly(request: AgentIngestRequest) -> dict[str, Any]:
    """Use the AWS ingestion tool without depending on its SDK wrapper shape."""
    try:
        try:
            from . import tools as research_tools
        except ImportError:
            import tools as research_tools
    except ImportError as exc:
        raise RuntimeError(f"Research ingestion tools are unavailable: {exc}") from exc

    if not os.getenv("SIDECHART_API_ENDPOINT") or not os.getenv("SIDECHART_API_KEY"):
        return {
            "success": False,
            "error": "SIDECHART API not configured. Running in local mode.",
        }

    document = {
        "text": request.analysis,
        "metadata": {
            "topic": request.topic,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    }
    result = research_tools.ingest_with_retries(document)
    return {
        "success": True,
        "document_id": result.get("document_id"),
        "message": f"Successfully ingested analysis for {request.topic}",
    }


@app.get("/")
async def root():
    return {
        "service": "SideChart Researcher",
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
        "api_compatibility": "local-sidechart-backend",
        "services": [
            "research",
            "chat",
            "market-data",
            "signals",
            "pipeline",
            "rebalance",
            "portfolio",
            "broker",
            "orders",
            "execution",
            "agents",
        ],
    }


@app.post("/research")
async def research(request: ResearchRequest) -> str:
    try:
        return await run_research_agent(request.topic)
    except Exception as exc:
        logger.exception("Research endpoint failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/research/auto")
async def research_auto():
    try:
        response = await run_research_agent(topic=None)
        return {
            "status": "success",
            "timestamp": datetime.now(UTC).isoformat(),
            "message": "Automated research completed",
            "preview": response[:200] + "..." if len(response) > 200 else response,
        }
    except Exception as exc:
        logger.exception("Automated research failed")
        return {
            "status": "error",
            "timestamp": datetime.now(UTC).isoformat(),
            "error": str(exc),
        }


@app.get("/health")
async def health():
    container_indicators = {
        "dockerenv": os.path.exists("/.dockerenv"),
        "containerenv": os.path.exists("/run/.containerenv"),
        "aws_execution_env": os.environ.get("AWS_EXECUTION_ENV", ""),
        "ecs_container_metadata": os.environ.get("ECS_CONTAINER_METADATA_URI", ""),
        "kubernetes_service": os.environ.get("KUBERNETES_SERVICE_HOST", ""),
    }
    return {
        "service": "SideChart Researcher",
        "status": "healthy",
        "sidechart_api_configured": bool(
            os.getenv("SIDECHART_API_ENDPOINT") and os.getenv("SIDECHART_API_KEY")
        ),
        "timestamp": datetime.now(UTC).isoformat(),
        "debug_container": container_indicators,
        "aws_region": os.environ.get("AWS_DEFAULT_REGION", "not set"),
        "bedrock_model": os.environ.get(
            "RESEARCHER_MODEL", "bedrock/converse/openai.gpt-oss-120b-1:0"
        ),
        "mcp_logging_enabled": MCP_LOGGING_ENABLED,
        "local_api_router_loaded": bool(_LOCAL_API_ROUTER_LOADED),
    }


@app.get("/test-bedrock")
async def test_bedrock():
    """Test the Bedrock connection directly without changing the researcher flow."""
    session = None
    try:
        import boto3

        region = os.environ.get("BEDROCK_REGION", "us-west-2")
        model_id = os.environ.get(
            "RESEARCHER_MODEL", "bedrock/converse/openai.gpt-oss-120b-1:0"
        )
        os.environ["AWS_REGION_NAME"] = region
        os.environ["AWS_REGION"] = region
        os.environ["AWS_DEFAULT_REGION"] = region

        session = boto3.Session()
        actual_region = session.region_name
        boto3.client("bedrock-runtime", region_name=region)

        try:
            bedrock_client = boto3.client("bedrock", region_name=region)
            models = bedrock_client.list_foundation_models()
            available_models = [
                model["modelId"]
                for model in models["modelSummaries"]
                if "openai" in model["modelId"].lower()
            ]
        except Exception as list_error:
            available_models = f"Error listing: {list_error}"

        (
            agent_class,
            runner,
            _trace_context,
            model_class,
            _create_mcp_server,
            _ingest_tool,
        ) = _load_agent_runtime()
        model = model_class(model=model_id)
        agent = agent_class(
            name="Test Agent",
            instructions="You are a helpful assistant. Be very brief.",
            model=model,
        )
        result = await runner.run(agent, input="Say hello in 5 words or less", max_turns=1)
        return {
            "status": "success",
            "model": str(model.model),
            "region": actual_region,
            "response": result.final_output,
            "debug": {
                "boto3_session_region": actual_region,
                "available_openai_models": available_models,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "type": type(exc).__name__,
            "debug": {
                "boto3_session_region": session.region_name if session else "unknown",
                "env_vars": {
                    "AWS_REGION_NAME": os.environ.get("AWS_REGION_NAME"),
                    "AWS_REGION": os.environ.get("AWS_REGION"),
                    "AWS_DEFAULT_REGION": os.environ.get("AWS_DEFAULT_REGION"),
                },
            },
        }


@app.get("/agents/research/prompt")
async def get_research_agent_prompt():
    return {
        "prompt": "\n\n".join(
            [_agent_instructions().strip(), DEFAULT_RESEARCH_PROMPT.strip()]
        )
    }


@app.post("/agents/research/run")
async def run_research_compatible(request: ResearchAgentRunRequest):
    tickers = _normalize_tickers(request.tickers)
    prompt = f"""
Generate an institutional sell-side research output for the SideChart workflow.

Ticker universe:
{tickers or "Unavailable"}

User supplied research context:
{request.source_context or "No additional sell-side notes supplied."}

SideChart pipeline context:
{json.dumps(_compact_pipeline_results(request.pipeline_results), indent=2, default=str)}

Cover every supplied ticker in the coverage matrix and ticker-by-ticker notes.
Separate observed data from estimates, mark unavailable data explicitly, and
include an informational-analysis disclaimer.
""".strip()
    try:
        output = await run_research_agent(topic=prompt, tickers=tickers)
        return {"output": output}
    except Exception as exc:
        logger.exception("Compatible research agent endpoint failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/agents/supervisor/context")
async def get_supervisor_agent_context(request: SupervisorContextRequest):
    try:
        return {"context": _supervisor_context(request)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/agents/supervisor/run")
async def run_supervisor_compatible(request: SupervisorAgentRunRequest):
    try:
        context = _supervisor_context(request)
        instructions = (
            "You are the SideChart supervisor agent. Produce a clean, "
            "finance-professional rebalance memo with exactly two top-level "
            "sections: RebalanceProposal and Rationale. Use markdown tables "
            "for ticker and action details. Do not execute trades."
        )
        output = await run_research_agent(
            topic=context,
            instructions=instructions,
            tickers=_normalize_tickers(request.tickers),
        )
        return {"context": context, "output": output}
    except Exception as exc:
        logger.exception("Compatible supervisor endpoint failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/agents/ingest")
async def ingest_agent_document(request: AgentIngestRequest):
    try:
        return await asyncio.to_thread(_ingest_directly, request)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


_LOCAL_API_ROUTER_LOADED = False
try:
    # The repository-root image includes backend/server.py and src/. Including
    # its router gives AWS the exact local API contracts, including IBKR routes.
    from backend.server import app as local_app

    overlapping_paths = {
        "/",
        "/agents/research/prompt",
        "/agents/research/run",
        "/agents/supervisor/context",
        "/agents/supervisor/run",
        "/agents/ingest",
    }
    app.router.routes.extend(
        route
        for route in local_app.router.routes
        if isinstance(route, APIRoute) and route.path not in overlapping_paths
    )
    _LOCAL_API_ROUTER_LOADED = True
except Exception as exc:
    logger.warning("Local API router was not loaded: %s", exc)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
