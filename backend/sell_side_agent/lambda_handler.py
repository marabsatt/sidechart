"""AWS Lambda handler for the SideChart sell-side research agent."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

try:
    from .agent import run_sell_side_agent
    from .observability import observe
except ImportError:
    from agent import run_sell_side_agent
    from observability import observe


logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _event_payload(event: Any) -> dict[str, Any]:
    if isinstance(event, str):
        event = json.loads(event)
    if not isinstance(event, dict):
        raise ValueError("Lambda event must be a JSON object.")
    body = event.get("body")
    if isinstance(body, str):
        return json.loads(body)
    if isinstance(body, dict):
        return body
    return event


def lambda_handler(event, context):
    """Run sell-side research for optional ``topic`` and ``tickers`` inputs."""
    del context
    with observe():
        try:
            payload = _event_payload(event)
            tickers = payload.get("tickers")
            if tickers is not None and not isinstance(tickers, list):
                raise ValueError("tickers must be a JSON array when provided.")
            result = asyncio.run(
                run_sell_side_agent(
                    topic=payload.get("topic"),
                    tickers=tickers,
                )
            )
            return {
                "statusCode": 200,
                "body": json.dumps({"success": True, **result}, default=str),
            }
        except ValueError as exc:
            return {"statusCode": 400, "body": json.dumps({"error": str(exc)})}
        except Exception as exc:
            logger.exception("Sell-side Lambda failed")
            return {
                "statusCode": 500,
                "body": json.dumps({"success": False, "error": str(exc)}),
            }
