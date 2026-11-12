"""Versioned messages exchanged by the connector."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
import uuid


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class OrderCommand:
    command_id: str
    order_id: str
    supervisor_review_id: str
    account_mode: str
    ticker: str
    action: str
    order_type: str
    quantity: int
    created_at: str
    expires_at: str
    limit_price: str | None = None
    stop_price: str | None = None
    schema_version: int = 1

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OrderCommand":
        required = {
            "command_id", "order_id", "supervisor_review_id", "account_mode",
            "ticker", "action", "order_type", "quantity", "created_at", "expires_at",
        }
        missing = sorted(required.difference(payload))
        if missing:
            raise ValueError(f"Command is missing fields: {', '.join(missing)}")
        command = cls(**{key: payload.get(key) for key in cls.__dataclass_fields__})
        command.validate()
        return command

    def validate(self) -> None:
        for value, name in ((self.command_id, "command_id"), (self.order_id, "order_id"),
                            (self.supervisor_review_id, "supervisor_review_id")):
            try:
                uuid.UUID(str(value))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{name} must be a UUID") from exc
        if self.schema_version != 1:
            raise ValueError(f"Unsupported command schema version {self.schema_version}")
        if self.account_mode not in {"PAPER", "LIVE"}:
            raise ValueError("account_mode must be PAPER or LIVE")
        if self.action not in {"BUY", "SELL"}:
            raise ValueError("action must be BUY or SELL")
        if self.order_type not in {"MKT", "LMT", "STP"}:
            raise ValueError("order_type must be MKT, LMT, or STP")
        if not self.ticker or not self.ticker.replace(".", "").replace("-", "").isalnum():
            raise ValueError("ticker contains unsupported characters")
        if isinstance(self.quantity, bool) or int(self.quantity) != self.quantity or self.quantity <= 0:
            raise ValueError("quantity must be a positive whole number")
        if self.order_type == "LMT" and self._positive_decimal(self.limit_price, "limit_price") is None:
            raise ValueError("LMT orders require limit_price")
        if self.order_type == "STP" and self._positive_decimal(self.stop_price, "stop_price") is None:
            raise ValueError("STP orders require stop_price")
        parse_time(self.created_at)
        if parse_time(self.expires_at) <= utc_now():
            raise ValueError("Command has expired")

    @staticmethod
    def _positive_decimal(value: str | None, name: str) -> Decimal | None:
        if value is None:
            return None
        try:
            parsed = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f"{name} must be numeric") from exc
        if parsed <= 0:
            raise ValueError(f"{name} must be positive")
        return parsed


@dataclass(frozen=True)
class BrokerEvent:
    connector_id: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    order_id: str | None = None
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: str = field(default_factory=lambda: utc_now().isoformat())
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
