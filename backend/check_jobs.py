#!/usr/bin/env python3
"""Query recent SideChart workflow jobs from the Aurora PostgreSQL database."""

from __future__ import annotations

import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent

RECENT_JOBS_SQL = """
WITH latest_review AS (
    SELECT DISTINCT ON (signal_id)
        id,
        signal_id,
        status,
        adjusted_quantity,
        adjusted_limit_price,
        reviewer_notes,
        reviewed_at
    FROM supervisor_reviews
    ORDER BY signal_id, reviewed_at DESC NULLS FIRST, id DESC
),
latest_order AS (
    SELECT DISTINCT ON (supervisor_review_id)
        id,
        supervisor_review_id,
        ib_order_id,
        ib_perm_id,
        action,
        order_type,
        status,
        total_qty,
        filled_qty,
        created_at
    FROM orders
    ORDER BY supervisor_review_id, created_at DESC, id DESC
),
execution_summary AS (
    SELECT
        order_id,
        COUNT(*)::INTEGER AS execution_count,
        COALESCE(SUM(shares), 0)::INTEGER AS executed_shares,
        COALESCE(SUM(commission), 0) AS total_commission,
        MAX(executed_at) AS last_executed_at
    FROM executions
    GROUP BY order_id
),
token_summary AS (
    SELECT
        signal_id,
        COALESCE(SUM(prompt_tokens), 0)::INTEGER AS prompt_tokens,
        COALESCE(SUM(completion_tokens), 0)::INTEGER AS completion_tokens,
        COALESCE(SUM(cost), 0) AS token_cost
    FROM agent_tokens_audit
    WHERE signal_id IS NOT NULL
    GROUP BY signal_id
)
SELECT
    signal.id::TEXT AS signal_id,
    signal.ticker,
    signal.signal_type,
    signal.suggested_price,
    signal.confidence_score,
    signal.analysis_metadata::TEXT AS analysis_metadata,
    signal.created_at,
    review.id::TEXT AS review_id,
    review.status AS review_status,
    review.adjusted_quantity,
    review.adjusted_limit_price,
    review.reviewer_notes,
    review.reviewed_at,
    trade_order.id::TEXT AS order_id,
    trade_order.ib_order_id,
    trade_order.ib_perm_id,
    trade_order.action,
    trade_order.order_type,
    trade_order.status AS order_status,
    trade_order.total_qty,
    trade_order.filled_qty,
    trade_order.created_at AS order_created_at,
    COALESCE(fill.execution_count, 0) AS execution_count,
    COALESCE(fill.executed_shares, 0) AS executed_shares,
    COALESCE(fill.total_commission, 0) AS total_commission,
    fill.last_executed_at,
    COALESCE(tokens.prompt_tokens, 0) AS prompt_tokens,
    COALESCE(tokens.completion_tokens, 0) AS completion_tokens,
    COALESCE(tokens.token_cost, 0) AS token_cost
FROM research_signals AS signal
LEFT JOIN latest_review AS review ON review.signal_id = signal.id
LEFT JOIN latest_order AS trade_order ON trade_order.supervisor_review_id = review.id
LEFT JOIN execution_summary AS fill ON fill.order_id = trade_order.id
LEFT JOIN token_summary AS tokens ON tokens.signal_id = signal.id
ORDER BY signal.created_at DESC
LIMIT :limit
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Show recent research-to-execution workflow jobs stored in Aurora."
        )
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of recent workflow jobs to return (default: 20).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the complete result as JSON instead of a readable summary.",
    )
    return parser.parse_args()


def _field_value(field: dict[str, Any]) -> Any:
    """Convert one Aurora Data API field into a normal Python value."""
    if field.get("isNull"):
        return None
    for key in (
        "stringValue",
        "longValue",
        "doubleValue",
        "booleanValue",
        "blobValue",
        "arrayValue",
    ):
        if key in field:
            return field[key]
    return None


def records_as_dicts(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Map a Data API response to dictionaries using its column metadata."""
    columns = [column["name"] for column in response.get("columnMetadata", [])]
    return [
        {
            column: _field_value(field)
            for column, field in zip(columns, record, strict=True)
        }
        for record in response.get("records", [])
    ]


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _metadata_summary(raw_metadata: Any) -> str:
    if not raw_metadata:
        return "none"
    try:
        metadata = json.loads(raw_metadata) if isinstance(raw_metadata, str) else raw_metadata
    except (TypeError, json.JSONDecodeError):
        return "present (not valid JSON)"
    if isinstance(metadata, dict):
        return ", ".join(sorted(metadata)) or "empty object"
    return type(metadata).__name__


def _display(value: Any, fallback: str = "N/A") -> Any:
    """Preserve meaningful zero values while formatting nullable fields."""
    return fallback if value is None else value


def print_jobs(jobs: list[dict[str, Any]]) -> None:
    """Print a compact view of each research-to-execution workflow."""
    if not jobs:
        print("No workflow jobs were found in the database.")
        return

    print(f"Retrieved {len(jobs)} workflow job(s) from Aurora.")
    for job in jobs:
        workflow_status = (
            job.get("order_status")
            or job.get("review_status")
            or "SIGNAL_CREATED"
        )
        print(f"\nSignal {job['signal_id']} [{workflow_status}]")
        print(
            f"  {job['ticker']} {job['signal_type']} | "
            f"created={job['created_at']} | "
            f"confidence={_display(job.get('confidence_score'))}"
        )
        print(f"  Analysis metadata: {_metadata_summary(job.get('analysis_metadata'))}")

        if job.get("review_id"):
            print(
                f"  Review: {job['review_status']} | "
                f"quantity={_display(job.get('adjusted_quantity'))} | "
                f"limit={_display(job.get('adjusted_limit_price'))} | "
                f"reviewed={_display(job.get('reviewed_at'), 'pending')}"
            )
        else:
            print("  Review: not created")

        if job.get("order_id"):
            print(
                f"  Order: {job['action']} {job['total_qty']} {job['ticker']} "
                f"({job['order_type']}) | status={job['order_status']} | "
                f"filled={job['filled_qty']}"
            )
            print(
                f"  Executions: {job['execution_count']} fill(s), "
                f"{job['executed_shares']} share(s), "
                f"commission={job['total_commission']}"
            )
        else:
            print("  Order: not created")

        print(
            f"  Tokens: prompt={job['prompt_tokens']}, "
            f"completion={job['completion_tokens']}, cost={job['token_cost']}"
        )


def main() -> int:
    args = parse_args()
    if args.limit < 1 or args.limit > 1000:
        print("--limit must be between 1 and 1000.", file=sys.stderr)
        return 2

    load_dotenv(REPOSITORY_ROOT / ".env", override=True)
    cluster_arn = os.environ.get("AURORA_CLUSTER_ARN")
    secret_arn = os.environ.get("AURORA_SECRET_ARN")
    database = os.environ.get("AURORA_DATABASE", "sidechart")
    region = os.environ.get("DEFAULT_AWS_REGION", "us-east-1")
    if not cluster_arn or not secret_arn:
        print(
            "Missing AURORA_CLUSTER_ARN or AURORA_SECRET_ARN in .env.",
            file=sys.stderr,
        )
        return 1

    client = boto3.client("rds-data", region_name=region)
    try:
        response = client.execute_statement(
            resourceArn=cluster_arn,
            secretArn=secret_arn,
            database=database,
            sql=RECENT_JOBS_SQL,
            parameters=[
                {"name": "limit", "value": {"longValue": args.limit}}
            ],
            includeResultMetadata=True,
        )
    except (BotoCoreError, ClientError) as exc:
        print(f"Unable to query workflow jobs: {exc}", file=sys.stderr)
        return 1

    jobs = records_as_dicts(response)
    if args.json:
        print(json.dumps(jobs, indent=2, default=_json_default))
    else:
        print_jobs(jobs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
