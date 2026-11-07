#!/usr/bin/env python3
"""Apply ordered PostgreSQL migrations through the Aurora Data API."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv


MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
STATEMENT_SEPARATOR = "-- migrate:split"


def split_migration(sql: str) -> list[str]:
    """Split a migration at explicit markers, preserving SQL function bodies."""
    return [
        statement.strip()
        for statement in sql.split(STATEMENT_SEPARATOR)
        if statement.strip()
    ]


def migration_files() -> list[Path]:
    """Return migration files in filename order."""
    return sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))


def execute(client, config: dict[str, str], sql: str, **kwargs):
    return client.execute_statement(**config, sql=sql, **kwargs)


def ensure_migration_ledger(client, config: dict[str, str]) -> None:
    execute(
        client,
        config,
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR(255) PRIMARY KEY,
            checksum CHAR(64) NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    )


def applied_migrations(client, config: dict[str, str]) -> dict[str, str]:
    response = execute(
        client,
        config,
        "SELECT version, checksum FROM schema_migrations ORDER BY version",
    )
    return {
        record[0]["stringValue"]: record[1]["stringValue"]
        for record in response.get("records", [])
    }


def apply_migration(
    client,
    config: dict[str, str],
    migration_path: Path,
    checksum: str,
) -> int:
    statements = split_migration(migration_path.read_text(encoding="utf-8"))
    transaction_id = client.begin_transaction(**config)["transactionId"]
    try:
        for statement in statements:
            execute(client, config, statement, transactionId=transaction_id)
        execute(
            client,
            config,
            """
            INSERT INTO schema_migrations (version, checksum)
            VALUES (:version, :checksum)
            """,
            transactionId=transaction_id,
            parameters=[
                {"name": "version", "value": {"stringValue": migration_path.name}},
                {"name": "checksum", "value": {"stringValue": checksum}},
            ],
        )
        client.commit_transaction(
            resourceArn=config["resourceArn"],
            secretArn=config["secretArn"],
            transactionId=transaction_id,
        )
        return len(statements)
    except Exception:
        client.rollback_transaction(
            resourceArn=config["resourceArn"],
            secretArn=config["secretArn"],
            transactionId=transaction_id,
        )
        raise


def main() -> int:
    load_dotenv(override=True)
    cluster_arn = os.environ.get("AURORA_CLUSTER_ARN")
    secret_arn = os.environ.get("AURORA_SECRET_ARN")
    database = os.environ.get("AURORA_DATABASE", "sidechart")
    region = os.environ.get("DEFAULT_AWS_REGION", "us-east-1")

    if not cluster_arn or not secret_arn:
        print("Missing AURORA_CLUSTER_ARN or AURORA_SECRET_ARN in the environment.")
        return 1

    files = migration_files()
    if not files:
        print(f"No migration files found in {MIGRATIONS_DIR}.")
        return 1

    client = boto3.client("rds-data", region_name=region)
    config = {
        "resourceArn": cluster_arn,
        "secretArn": secret_arn,
        "database": database,
    }

    print(f"Applying database migrations to {database} in {region}...")
    try:
        ensure_migration_ledger(client, config)
        applied = applied_migrations(client, config)
        applied_count = 0

        for path in files:
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            previous_checksum = applied.get(path.name)
            if previous_checksum:
                if previous_checksum != checksum:
                    raise RuntimeError(
                        f"Applied migration {path.name} has been modified; "
                        "create a new migration instead."
                    )
                print(f"  SKIP  {path.name}")
                continue

            statement_count = apply_migration(client, config, path, checksum)
            applied_count += 1
            print(f"  APPLY {path.name} ({statement_count} statements)")

        print(
            f"Migration complete: {applied_count} applied, "
            f"{len(files) - applied_count} skipped."
        )
        return 0
    except (BotoCoreError, ClientError, RuntimeError) as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
