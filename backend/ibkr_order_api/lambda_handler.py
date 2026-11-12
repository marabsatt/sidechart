"""Create one broker command from an approved supervisor review."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import os
from typing import Any
import uuid

import boto3


LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)
RDS = None
SQS = None
CONFIG = {
    "resourceArn": os.environ.get("AURORA_CLUSTER_ARN", ""),
    "secretArn": os.environ.get("AURORA_SECRET_ARN", ""),
    "database": os.getenv("AURORA_DATABASE", "sidechart"),
}
COMMAND_QUEUE_URL = os.environ.get("IBKR_COMMAND_QUEUE_URL", "")
COMMAND_TTL_SECONDS = int(os.getenv("IBKR_COMMAND_TTL_SECONDS", "300"))


class ApiError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _rds():
    global RDS
    if RDS is None:
        RDS = boto3.client(
            "rds-data", region_name=os.getenv("DEFAULT_AWS_REGION", "us-east-1")
        )
    return RDS


def _sqs():
    global SQS
    if SQS is None:
        SQS = boto3.client(
            "sqs", region_name=os.getenv("DEFAULT_AWS_REGION", "us-east-1")
        )
    return SQS


def _response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    body = event.get("body", event)
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ApiError(400, "Request body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise ApiError(400, "Request body must be a JSON object")
    return body


def _review_id(payload: dict[str, Any]) -> str:
    value = payload.get("supervisor_review_id")
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError) as exc:
        raise ApiError(400, "supervisor_review_id must be a UUID") from exc


def _value(field: dict[str, Any]) -> Any:
    if field.get("isNull"):
        return None
    for key in ("stringValue", "longValue", "doubleValue", "booleanValue"):
        if key in field:
            return field[key]
    return None


def _row(response: dict[str, Any]) -> dict[str, Any] | None:
    records = response.get("records", [])
    if not records:
        return None
    names = [column["name"] for column in response.get("columnMetadata", [])]
    return {name: _value(field) for name, field in zip(names, records[0])}


def _execute(
    sql: str,
    parameters: list[dict[str, Any]],
    transaction_id: str | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        **CONFIG,
        "sql": sql,
        "parameters": parameters,
        "includeResultMetadata": True,
    }
    if transaction_id:
        kwargs["transactionId"] = transaction_id
    return _rds().execute_statement(**kwargs)


def _string(name: str, value: str) -> dict[str, Any]:
    return {"name": name, "value": {"stringValue": value}}


def _load_review(review_id: str, transaction_id: str) -> dict[str, Any]:
    response = _execute(
        """
        SELECT
            sr.id::text AS supervisor_review_id,
            sr.status AS review_status,
            sr.adjusted_quantity,
            COALESCE(sr.adjusted_limit_price, rs.suggested_price)::text AS limit_price,
            sr.reviewed_at::text AS reviewed_at,
            rs.ticker,
            rs.signal_type
        FROM supervisor_reviews sr
        JOIN research_signals rs ON rs.id = sr.signal_id
        WHERE sr.id = CAST(:review_id AS UUID)
        FOR UPDATE OF sr
        """,
        [_string("review_id", review_id)],
        transaction_id,
    )
    review = _row(response)
    if review is None:
        raise ApiError(404, "Supervisor review was not found")
    if review["review_status"] not in {"APPROVED", "MODIFIED"}:
        raise ApiError(409, f"Supervisor review is {review['review_status']}, not approved")
    if not review.get("reviewed_at"):
        raise ApiError(409, "Supervisor review has no review timestamp")
    if review["signal_type"] not in {"BUY", "SELL"}:
        raise ApiError(409, "HOLD signals cannot create orders")
    if review.get("adjusted_quantity") is None:
        raise ApiError(409, "Approved review must specify adjusted_quantity")
    if review.get("limit_price") is None:
        raise ApiError(409, "Approved review must specify a limit price")
    return review


def _existing_order(review_id: str, transaction_id: str) -> dict[str, Any] | None:
    return _row(
        _execute(
            """
            SELECT id::text AS order_id, command_id::text AS command_id, status,
                   action, order_type, total_qty, limit_price::text AS limit_price,
                   created_at::text AS created_at
            FROM orders
            WHERE supervisor_review_id = CAST(:review_id AS UUID)
            """,
            [_string("review_id", review_id)],
            transaction_id,
        )
    )


def _insert_order(review: dict[str, Any], command_id: str, transaction_id: str) -> dict[str, Any]:
    response = _execute(
        """
        INSERT INTO orders (
            supervisor_review_id, command_id, action, order_type, status,
            total_qty, filled_qty, limit_price
        ) VALUES (
            CAST(:review_id AS UUID), CAST(:command_id AS UUID), :action, 'LMT',
            'QUEUEING', :quantity, 0, CAST(:limit_price AS NUMERIC)
        )
        RETURNING id::text AS order_id, command_id::text AS command_id, status,
                  action, order_type, total_qty, limit_price::text AS limit_price,
                  created_at::text AS created_at
        """,
        [
            _string("review_id", review["supervisor_review_id"]),
            _string("command_id", command_id),
            _string("action", review["signal_type"]),
            {"name": "quantity", "value": {"longValue": int(review["adjusted_quantity"])}},
            _string("limit_price", review["limit_price"]),
        ],
        transaction_id,
    )
    order = _row(response)
    if order is None:
        raise RuntimeError("Aurora did not return the created order")
    return order


def _set_status(order_id: str, status: str) -> None:
    _execute(
        "UPDATE orders SET status = :status, updated_at = NOW() WHERE id = CAST(:order_id AS UUID)",
        [_string("status", status), _string("order_id", order_id)],
    )


def _command(review: dict[str, Any], order: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "schema_version": 1,
        "command_id": order["command_id"],
        "order_id": order["order_id"],
        "supervisor_review_id": review["supervisor_review_id"],
        "account_mode": os.getenv("IBKR_ACCOUNT_MODE", "PAPER").upper(),
        "ticker": review["ticker"].upper(),
        "action": order["action"],
        "order_type": order["order_type"],
        "quantity": int(order["total_qty"]),
        "limit_price": order["limit_price"],
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=COMMAND_TTL_SECONDS)).isoformat(),
    }


def create_approved_order(review_id: str) -> tuple[dict[str, Any], bool]:
    if not COMMAND_QUEUE_URL:
        raise RuntimeError("IBKR_COMMAND_QUEUE_URL is not configured")
    client = _rds()
    transaction_id = client.begin_transaction(**CONFIG)["transactionId"]
    created = False
    try:
        review = _load_review(review_id, transaction_id)
        order = _existing_order(review_id, transaction_id)
        if order is None:
            order = _insert_order(review, str(uuid.uuid4()), transaction_id)
            created = True
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

    if not created and order["status"] != "QUEUE_FAILED":
        return order, False

    try:
        command = _command(review, order)
        _sqs().send_message(
            QueueUrl=COMMAND_QUEUE_URL,
            MessageBody=json.dumps(command, separators=(",", ":")),
            MessageGroupId=review_id,
            MessageDeduplicationId=order["command_id"],
        )
        _set_status(order["order_id"], "QUEUED")
        order["status"] = "QUEUED"
        return order, True
    except Exception:
        _set_status(order["order_id"], "QUEUE_FAILED")
        raise


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    del context
    try:
        review_id = _review_id(_payload(event))
        order, queued = create_approved_order(review_id)
        return _response(
            202 if queued else 200,
            {
                "order": order,
                "queued": queued,
                "message": "Approved order queued for the local IBKR connector"
                if queued
                else "This supervisor review already has an order",
            },
        )
    except ApiError as exc:
        return _response(exc.status_code, {"error": str(exc)})
    except Exception:
        LOGGER.exception("Approved-order API failed")
        return _response(500, {"error": "Unable to create approved order"})
