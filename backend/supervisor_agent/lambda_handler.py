"""AWS Lambda handler for the SideChart supervisor agent."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

try:
    from .agent import run_supervisor_agent
    from .observability import observe
except ImportError:
    from agent import run_supervisor_agent
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


def _positive_integer(payload: dict[str, Any], key: str, default: int) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{key} must be a positive integer.")
    return value


def lambda_handler(event, context):
    """Run supervisor synthesis over research and pipeline inputs."""
    del context
    with observe():
        try:
            payload = _event_payload(event)
            tickers = payload.get("tickers")
            if tickers is not None and not isinstance(tickers, list):
                raise ValueError("tickers must be a JSON array when provided.")
            pipeline_results = payload.get("pipeline_results")
            if pipeline_results is not None and not isinstance(pipeline_results, dict):
                raise ValueError("pipeline_results must be a JSON object when provided.")

            result = asyncio.run(
                run_supervisor_agent(
                    tickers=tickers,
                    sellside_research=payload.get("sellside_research"),
                    pipeline_results=pipeline_results,
                    current_positions=payload.get("current_positions"),
                    lookback_months=_positive_integer(payload, "lookback_months", 3),
                    num_signals=_positive_integer(payload, "num_signals", 20),
                    task=payload.get("task"),
                )
            )
            return {
                "statusCode": 200,
                "body": json.dumps({"success": True, **result}, default=str),
            }
        except ValueError as exc:
            return {"statusCode": 400, "body": json.dumps({"error": str(exc)})}
        except Exception as exc:
            logger.exception("Supervisor Lambda failed")
            return {
                "statusCode": 500,
                "body": json.dumps({"success": False, "error": str(exc)}),
            }
