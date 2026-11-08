"""Playwright MCP configuration shared with the local supervisor agent."""

from src.agents.supervisor.mcp_servers import (
    LoggingMCPServerStdio,
    create_playwright_mcp_server,
)


__all__ = ["LoggingMCPServerStdio", "create_playwright_mcp_server"]
