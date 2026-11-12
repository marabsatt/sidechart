"""Persist connector events in Aurora through the RDS Data API."""

from __future__ import annotations

import json
import os
from typing import Any

import boto3


RDS = None
CONFIG = {
    "resourceArn": os.environ.get("AURORA_CLUSTER_ARN", ""),
    "secretArn": os.environ.get("AURORA_SECRET_ARN", ""),
    "database": os.getenv("AURORA_DATABASE", "sidechart"),
}


def _string(name: str, value: Any) -> dict[str, Any]:
    return {"name": name, "value": {"isNull": True} if value is None else {"stringValue": str(value)}}


def _integer(name: str, value: Any) -> dict[str, Any]:
    return {"name": name, "value": {"isNull": True} if value is None else {"longValue": int(value)}}


def _execute(sql: str, parameters: list[dict[str, Any]], transaction_id: str) -> dict[str, Any]:
    return _rds().execute_statement(
        **CONFIG,
        transactionId=transaction_id,
        sql=sql,
        parameters=parameters,
    )


def _rds():
    global RDS
    if RDS is None:
        RDS = boto3.client(
            "rds-data", region_name=os.getenv("DEFAULT_AWS_REGION", "us-east-1")
        )
    return RDS


def _record_event(event: dict[str, Any], transaction_id: str) -> bool:
    payload = event.get("payload") or {}
    connector_id = event["connector_id"]
    _execute(
        """
        INSERT INTO broker_connectors (
            connector_id, account_mode, status, gateway_port, client_id, version,
            last_heartbeat_at, last_connected_at, last_error, metadata, updated_at
        ) VALUES (
            :connector_id, :account_mode, :status, :gateway_port, :client_id, :version,
            CAST(:occurred_at AS TIMESTAMPTZ),
            CASE WHEN :status = 'CONNECTED' THEN CAST(:occurred_at AS TIMESTAMPTZ) END,
            :last_error, CAST(:metadata AS JSONB), NOW()
        )
        ON CONFLICT (connector_id) DO UPDATE SET
            account_mode = EXCLUDED.account_mode,
            status = EXCLUDED.status,
            gateway_port = EXCLUDED.gateway_port,
            client_id = EXCLUDED.client_id,
            version = EXCLUDED.version,
            last_heartbeat_at = EXCLUDED.last_heartbeat_at,
            last_connected_at = COALESCE(EXCLUDED.last_connected_at, broker_connectors.last_connected_at),
            last_error = COALESCE(EXCLUDED.last_error, broker_connectors.last_error),
            metadata = EXCLUDED.metadata,
            updated_at = NOW()
        """,
        [
            _string("connector_id", connector_id),
            _string("account_mode", payload.get("account_mode", "PAPER")),
            _string("status", _connector_status(event["event_type"], payload)),
            _integer("gateway_port", payload.get("gateway_port")),
            _integer("client_id", payload.get("client_id")),
            _string("version", payload.get("version")),
            _string("occurred_at", event["occurred_at"]),
            _string("last_error", payload.get("message") if event["event_type"] == "ERROR" else None),
            _string("metadata", json.dumps({"last_event_type": event["event_type"]})),
        ],
        transaction_id,
    )
    response = _execute(
        """
        INSERT INTO broker_events (
            event_id, connector_id, event_type, order_id, payload, occurred_at
        ) VALUES (
            CAST(:event_id AS UUID), :connector_id, :event_type,
            CAST(:order_id AS UUID), CAST(:payload AS JSONB), CAST(:occurred_at AS TIMESTAMPTZ)
        )
        ON CONFLICT (event_id) DO NOTHING
        RETURNING id
        """,
        [
            _string("event_id", event["event_id"]),
            _string("connector_id", connector_id),
            _string("event_type", event["event_type"]),
            _string("order_id", event.get("order_id")),
            _string("payload", json.dumps(payload, separators=(",", ":"), default=str)),
            _string("occurred_at", event["occurred_at"]),
        ],
        transaction_id,
    )
    return bool(response.get("records"))


def _connector_status(event_type: str, payload: dict[str, Any]) -> str:
    if event_type in {"CONNECTED", "HEARTBEAT"}:
        return payload.get("status", "CONNECTED")
    if event_type == "DISCONNECTED":
        return "DISCONNECTED"
    if event_type == "ERROR":
        return "DEGRADED"
    return payload.get("status") if payload.get("status") in {
        "CONNECTED", "DISCONNECTED", "DEGRADED", "OFFLINE"
    } else "CONNECTED"


def _apply_domain_event(event: dict[str, Any], transaction_id: str) -> None:
    event_type = event["event_type"]
    payload = event.get("payload") or {}
    order_id = event.get("order_id")
    if event_type in {"ORDER_ACK", "ORDER_STATUS"} and order_id:
        _execute(
            """
            UPDATE orders SET
                ib_order_id = COALESCE(:ib_order_id, ib_order_id),
                ib_perm_id = COALESCE(:ib_perm_id, ib_perm_id),
                status = COALESCE(:status, status),
                filled_qty = COALESCE(:filled_qty, filled_qty),
                updated_at = NOW()
            WHERE id = CAST(:order_id AS UUID)
            """,
            [
                _integer("ib_order_id", payload.get("ib_order_id")),
                _integer("ib_perm_id", payload.get("ib_perm_id")),
                _string("status", payload.get("status")),
                _integer("filled_qty", payload.get("filled_qty")),
                _string("order_id", order_id),
            ],
            transaction_id,
        )
    elif event_type == "EXECUTION" and order_id:
        _execute(
            """
            INSERT INTO executions (order_id, ib_exec_id, price, shares, executed_at)
            VALUES (
                CAST(:order_id AS UUID), :ib_exec_id, CAST(:price AS NUMERIC), :shares,
                CAST(:executed_at AS TIMESTAMPTZ)
            )
            ON CONFLICT (ib_exec_id) DO UPDATE SET
                price = EXCLUDED.price, shares = EXCLUDED.shares,
                executed_at = EXCLUDED.executed_at
            """,
            [
                _string("order_id", order_id),
                _string("ib_exec_id", payload["ib_exec_id"]),
                _string("price", payload["price"]),
                _integer("shares", payload["shares"]),
                _string("executed_at", payload["executed_at"]),
            ],
            transaction_id,
        )
    elif event_type == "COMMISSION":
        _execute(
            "UPDATE executions SET commission = CAST(:commission AS NUMERIC) WHERE ib_exec_id = :ib_exec_id",
            [_string("commission", payload.get("commission")), _string("ib_exec_id", payload["ib_exec_id"])],
            transaction_id,
        )
    elif event_type == "POSITION":
        _execute(
            """
            INSERT INTO portfolio_positions (
                ticker, position_size, average_cost, market_value, unrealized_pnl, updated_at
            ) VALUES (:ticker, :position_size, CAST(:average_cost AS NUMERIC), 0, 0, NOW())
            ON CONFLICT (ticker) DO UPDATE SET
                position_size = EXCLUDED.position_size,
                average_cost = EXCLUDED.average_cost,
                updated_at = NOW()
            """,
            [
                _string("ticker", str(payload["ticker"]).upper()),
                _integer("position_size", payload["position_size"]),
                _string("average_cost", payload["average_cost"]),
            ],
            transaction_id,
        )


def process_event(event: dict[str, Any]) -> None:
    required = {"event_id", "connector_id", "event_type", "occurred_at", "payload"}
    missing = required.difference(event)
    if missing:
        raise ValueError(f"Broker event is missing fields: {sorted(missing)}")
    client = _rds()
    transaction_id = client.begin_transaction(**CONFIG)["transactionId"]
    try:
        if _record_event(event, transaction_id):
            _apply_domain_event(event, transaction_id)
        client.commit_transaction(
            resourceArn=CONFIG["resourceArn"],
            secretArn=CONFIG["secretArn"],
            transactionId=transaction_id,
        )
    except Exception:
        client.rollback_transaction(
            resourceArn=CONFIG["resourceArn"],
            secretArn=CONFIG["secretArn"],
            transactionId=transaction_id,
        )
        raise


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    failures = []
    for record in event.get("Records", []):
        try:
            process_event(json.loads(record["body"]))
        except Exception:
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
