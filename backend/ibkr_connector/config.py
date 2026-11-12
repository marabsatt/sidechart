"""Environment-backed connector configuration."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ConnectorConfig:
    command_queue_url: str
    event_queue_url: str
    aws_region: str = "us-east-1"
    aws_profile: str | None = None
    connector_id: str = "sidechart-local"
    ib_host: str = "127.0.0.1"
    ib_port: int = 4002
    ib_client_id: int = 31
    account_mode: str = "PAPER"
    allow_live_trading: bool = False
    max_order_quantity: int = 1000
    heartbeat_seconds: int = 30
    journal_path: Path = Path(".sidechart/ibkr_connector.sqlite3")
    kill_switch_path: Path = Path(".sidechart/IBKR_KILL_SWITCH")

    @classmethod
    def from_env(cls) -> "ConnectorConfig":
        command_queue_url = os.getenv("IBKR_COMMAND_QUEUE_URL", "").strip()
        event_queue_url = os.getenv("IBKR_EVENT_QUEUE_URL", "").strip()
        if not command_queue_url or not event_queue_url:
            raise ValueError("IBKR_COMMAND_QUEUE_URL and IBKR_EVENT_QUEUE_URL are required")

        mode = os.getenv("IBKR_ACCOUNT_MODE", "PAPER").strip().upper()
        if mode not in {"PAPER", "LIVE"}:
            raise ValueError("IBKR_ACCOUNT_MODE must be PAPER or LIVE")
        allow_live = _bool("IBKR_ALLOW_LIVE_TRADING")
        if mode == "LIVE" and not allow_live:
            raise ValueError("LIVE mode requires IBKR_ALLOW_LIVE_TRADING=true")

        default_port = 4001 if mode == "LIVE" else 4002
        return cls(
            command_queue_url=command_queue_url,
            event_queue_url=event_queue_url,
            aws_region=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1")),
            aws_profile=os.getenv("AWS_PROFILE") or None,
            connector_id=os.getenv("IBKR_CONNECTOR_ID", "sidechart-local").strip(),
            ib_host=os.getenv("IB_HOST", "127.0.0.1").strip(),
            ib_port=int(os.getenv("IB_PORT", str(default_port))),
            ib_client_id=int(os.getenv("IB_CLIENT_ID", "31")),
            account_mode=mode,
            allow_live_trading=allow_live,
            max_order_quantity=int(os.getenv("IBKR_MAX_ORDER_QUANTITY", "1000")),
            heartbeat_seconds=int(os.getenv("IBKR_HEARTBEAT_SECONDS", "30")),
            journal_path=Path(os.getenv("IBKR_JOURNAL_PATH", ".sidechart/ibkr_connector.sqlite3")),
            kill_switch_path=Path(os.getenv("IBKR_KILL_SWITCH_PATH", ".sidechart/IBKR_KILL_SWITCH")),
        )

    def validate(self) -> None:
        if not self.connector_id:
            raise ValueError("IBKR_CONNECTOR_ID cannot be blank")
        if self.max_order_quantity <= 0:
            raise ValueError("IBKR_MAX_ORDER_QUANTITY must be positive")
        expected_port = 4001 if self.account_mode == "LIVE" else 4002
        if self.ib_port != expected_port:
            raise ValueError(
                f"{self.account_mode} IB Gateway must use port {expected_port}; got {self.ib_port}"
            )
