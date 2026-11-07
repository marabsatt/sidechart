#!/usr/bin/env python3
"""Verify the exact SideChart HITL trading schema in Aurora PostgreSQL."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import boto3
from dotenv import load_dotenv


EXPECTED_COLUMNS = {
    "research_signals": {
        "id",
        "ticker",
        "signal_type",
        "suggested_price",
        "confidence_score",
        "analysis_metadata",
        "created_at",
    },
    "supervisor_reviews": {
        "id",
        "signal_id",
        "status",
        "adjusted_quantity",
        "adjusted_limit_price",
        "reviewer_notes",
        "reviewed_at",
    },
    "orders": {
        "id",
        "supervisor_review_id",
        "ib_order_id",
        "ib_perm_id",
        "action",
        "order_type",
        "status",
        "total_qty",
        "filled_qty",
        "created_at",
    },
    "executions": {
        "id",
        "order_id",
        "ib_exec_id",
        "price",
        "shares",
        "commission",
        "executed_at",
    },
    "portfolio_positions": {
        "ticker",
        "position_size",
        "average_cost",
        "market_value",
        "unrealized_pnl",
        "updated_at",
    },
    "agent_tokens_audit": {
        "id",
        "agent_name",
        "signal_id",
        "prompt_tokens",
        "completion_tokens",
        "cost",
    },
}


def main() -> int:
    repository_root = Path(__file__).resolve().parents[2]
    load_dotenv(repository_root / ".env", override=True)
    cluster_arn = os.environ.get("AURORA_CLUSTER_ARN")
    secret_arn = os.environ.get("AURORA_SECRET_ARN")
    database = os.environ.get("AURORA_DATABASE", "sidechart")
    region = os.environ.get("DEFAULT_AWS_REGION", "us-east-1")
    if not cluster_arn or not secret_arn:
        print("Missing AURORA_CLUSTER_ARN or AURORA_SECRET_ARN.", file=sys.stderr)
        return 1

    client = boto3.client("rds-data", region_name=region)
    response = client.execute_statement(
        resourceArn=cluster_arn,
        secretArn=secret_arn,
        database=database,
        sql="""
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
        """,
    )
    actual_columns: dict[str, set[str]] = {}
    for record in response.get("records", []):
        table_name = record[0]["stringValue"]
        column_name = record[1]["stringValue"]
        actual_columns.setdefault(table_name, set()).add(column_name)

    application_columns = {
        table: columns
        for table, columns in actual_columns.items()
        if table != "schema_migrations"
    }
    if application_columns != EXPECTED_COLUMNS:
        print("Schema mismatch.", file=sys.stderr)
        print(f"Expected: {EXPECTED_COLUMNS}", file=sys.stderr)
        print(f"Actual: {application_columns}", file=sys.stderr)
        return 1

    print("Schema verified: 6 application tables with the exact expected columns.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
