"""Playwright MCP configuration shared with the local research agent."""

from src.agents.research.mcp_servers import (
    LoggingMCPServerStdio,
    create_playwright_mcp_server,
)


__all__ = ["LoggingMCPServerStdio", "create_playwright_mcp_server"]
