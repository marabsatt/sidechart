"""Supervisor prompt templates shared with the local supervisor agent."""

from src.agents.supervisor.context import (
    DEFAULT_RESEARCH_PROMPT_FALLBACK,
    build_rebalance_proposal_context,
    supervisor_agent,
)


__all__ = [
    "DEFAULT_RESEARCH_PROMPT_FALLBACK",
    "build_rebalance_proposal_context",
    "supervisor_agent",
]
