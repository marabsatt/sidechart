"""Narrow SQS adapter used by the local connector."""

from __future__ import annotations

import json
from typing import Any

import boto3

from .config import ConnectorConfig


class AwsQueues:
    def __init__(self, config: ConnectorConfig):
        session_args: dict[str, str] = {"region_name": config.aws_region}
        if config.aws_profile:
            session_args["profile_name"] = config.aws_profile
        self.client = boto3.Session(**session_args).client("sqs")
        self.command_queue_url = config.command_queue_url
        self.event_queue_url = config.event_queue_url

    def receive_command(self) -> dict[str, Any] | None:
        response = self.client.receive_message(
            QueueUrl=self.command_queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            VisibilityTimeout=60,
            AttributeNames=["ApproximateReceiveCount"],
        )
        messages = response.get("Messages", [])
        return messages[0] if messages else None

    def delete_command(self, receipt_handle: str) -> None:
        self.client.delete_message(
            QueueUrl=self.command_queue_url,
            ReceiptHandle=receipt_handle,
        )

    def publish_event(self, event: dict[str, Any]) -> None:
        group_id = event.get("order_id") or event["connector_id"]
        self.client.send_message(
            QueueUrl=self.event_queue_url,
            MessageBody=json.dumps(event, separators=(",", ":"), default=str),
            MessageGroupId=str(group_id),
            MessageDeduplicationId=event["event_id"],
        )
