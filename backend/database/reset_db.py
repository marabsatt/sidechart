#!/usr/bin/env python3
"""Drop and recreate the SideChart HITL trading schema."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import boto3
from dotenv import load_dotenv


APPLICATION_TABLES = (
    "executions",
    "orders",
    "agent_tokens_audit",
    "supervisor_reviews",
    "research_signals",
    "portfolio_positions",
)
DATABASE_DIR = Path(__file__).resolve().parent


def main() -> int:
    load_dotenv(DATABASE_DIR.parent.parent / ".env", override=True)
    cluster_arn = os.environ.get("AURORA_CLUSTER_ARN")
    secret_arn = os.environ.get("AURORA_SECRET_ARN")
    database = os.environ.get("AURORA_DATABASE", "sidechart")
    region = os.environ.get("DEFAULT_AWS_REGION", "us-east-1")
    if not cluster_arn or not secret_arn:
        print("Missing AURORA_CLUSTER_ARN or AURORA_SECRET_ARN.", file=sys.stderr)
        return 1

    client = boto3.client("rds-data", region_name=region)
    config = {
        "resourceArn": cluster_arn,
        "secretArn": secret_arn,
        "database": database,
    }
    transaction_id = client.begin_transaction(**config)["transactionId"]
    try:
        table_names = ", ".join((*APPLICATION_TABLES, "schema_migrations"))
        client.execute_statement(
            **config,
            transactionId=transaction_id,
            sql=f"DROP TABLE IF EXISTS {table_names} CASCADE",
        )
        client.commit_transaction(
            resourceArn=cluster_arn,
            secretArn=secret_arn,
            transactionId=transaction_id,
        )
    except Exception:
        client.rollback_transaction(
            resourceArn=cluster_arn,
            secretArn=secret_arn,
            transactionId=transaction_id,
        )
        raise

    result = subprocess.run(
        [sys.executable, str(DATABASE_DIR / "run_migrations.py")],
        cwd=DATABASE_DIR.parent.parent,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
