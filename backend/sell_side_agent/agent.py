"""Sell-side research agent runtime for AWS Lambda."""

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
    from .templates import DEFAULT_RESEARCH_PROMPT, sellside_agent_instructions
    from .tools import SELL_SIDE_TOOLS
except ImportError:
    from mcp_servers import create_playwright_mcp_server
    from templates import DEFAULT_RESEARCH_PROMPT, sellside_agent_instructions
    from tools import SELL_SIDE_TOOLS


def _model_name() -> str:
    configured = os.getenv("SELL_SIDE_MODEL") or os.getenv("BEDROCK_MODEL_ID")
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


async def run_sell_side_agent(
    topic: str | None = None,
    tickers: list[str] | None = None,
) -> dict[str, Any]:
    """Run the local sell-side behavior inside the Lambda container."""
    normalized_tickers = sorted(
        {ticker.strip().upper() for ticker in tickers or [] if ticker.strip()}
    )
    instructions = sellside_agent_instructions(normalized_tickers or None)
    query = (
        f"Research this investment topic: {topic.strip()}"
        if topic and topic.strip()
        else DEFAULT_RESEARCH_PROMPT
    )

    async with create_playwright_mcp_server(timeout_seconds=120) as playwright_mcp:
        agent = Agent(
            name="SideChart Sell-side Researcher",
            instructions=instructions,
            model=create_model(),
            tools=SELL_SIDE_TOOLS,
            mcp_servers=[playwright_mcp],
        )
        with trace("Sell-side Research Agent"):
            result = await Runner.run(
                agent,
                input=query,
                max_turns=int(os.getenv("SELL_SIDE_MAX_TURNS", "30")),
            )

    return {
        "agent": "sell_side_agent",
        "tickers": normalized_tickers,
        "output": result.final_output,
    }
