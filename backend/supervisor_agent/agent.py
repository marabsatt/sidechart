"""Supervisor agent runtime for AWS Lambda."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any

from agents import Agent, Runner, trace
from agents.extensions.models.litellm_model import LitellmModel


if __package__ in (None, ""):
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "src").is_dir():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            break

try:
    from .mcp_servers import create_playwright_mcp_server
    from .templates import supervisor_agent
    from .tools import SUPERVISOR_TOOLS
except ImportError:
    from mcp_servers import create_playwright_mcp_server
    from templates import supervisor_agent
    from tools import SUPERVISOR_TOOLS


DEFAULT_SUPERVISOR_TASK = """
Review the supplied research, signals, current positions, and draft weights.
Return the RebalanceProposal and Rationale sections exactly as specified in
your instructions. Do not execute trades.
""".strip()


def _model_name() -> str:
    configured = os.getenv("SUPERVISOR_MODEL") or os.getenv("BEDROCK_MODEL_ID")
    if not configured:
        configured = "converse/openai.gpt-oss-120b-1:0"
    if "/" not in configured:
        configured = f"bedrock/{configured}"
    elif not configured.startswith("bedrock/"):
        configured = f"bedrock/{configured}"
    return configured


def create_model() -> LitellmModel:
    """Create the configured Bedrock model adapter."""
    region = os.getenv("BEDROCK_REGION", "us-east-1")
    os.environ["AWS_REGION_NAME"] = region
    os.environ["AWS_REGION"] = region
    os.environ["AWS_DEFAULT_REGION"] = region
    return LitellmModel(model=_model_name())


async def run_supervisor_agent(
    *,
    tickers: list[str] | None = None,
    sellside_research: str | None = None,
    pipeline_results: dict[str, Any] | None = None,
    current_positions: Any = None,
    lookback_months: int = 3,
    num_signals: int = 20,
    task: str | None = None,
) -> dict[str, Any]:
    """Run the local supervisor behavior inside the Lambda container."""
    normalized_tickers = sorted(
        {ticker.strip().upper() for ticker in tickers or [] if ticker.strip()}
    )
    instructions = supervisor_agent(
        tickers=normalized_tickers or None,
        sellside_research=sellside_research,
        pipeline_results=pipeline_results,
        current_positions=current_positions,
        lookback_months=lookback_months,
        num_signals=num_signals,
    )

    async with create_playwright_mcp_server(timeout_seconds=120) as playwright_mcp:
        agent = Agent(
            name="SideChart Supervisor",
            instructions=instructions,
            model=create_model(),
            tools=SUPERVISOR_TOOLS,
            mcp_servers=[playwright_mcp],
        )
        with trace("Supervisor Agent"):
            result = await Runner.run(
                agent,
                input=task.strip() if task and task.strip() else DEFAULT_SUPERVISOR_TASK,
                max_turns=int(os.getenv("SUPERVISOR_MAX_TURNS", "30")),
            )

    return {
        "agent": "supervisor_agent",
        "tickers": normalized_tickers,
        "output": result.final_output,
    }
