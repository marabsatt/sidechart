#!/usr/bin/env python3
"""Build and optionally push one SideChart Lambda container image."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
AGENTS = {
    "planner": {
        "directory": "planner",
        "repository": "sidechart-planner",
        "function": "sidechart-planner",
    },
    "classifier": {
        "directory": "classifier",
        "repository": "sidechart-classifier",
        "function": "sidechart-classifier",
    },
    "reporter": {
        "directory": "reporter",
        "repository": "sidechart-reporter",
        "function": "sidechart-reporter",
    },
    "charter": {
        "directory": "charter",
        "repository": "sidechart-charter",
        "function": "sidechart-charter",
    },
    "sell_side_agent": {
        "directory": "sell_side_agent",
        "repository": "sidechart-sell-side-agent",
        "function": "sidechart-sell-side-agent",
    },
    "supervisor_agent": {
        "directory": "supervisor_agent",
        "repository": "sidechart-supervisor-agent",
        "function": "sidechart-supervisor-agent",
    },
    "ibkr_event_processor": {
        "directory": "ibkr_event_processor",
        "repository": "sidechart-ibkr-event-processor",
        "function": "sidechart-ibkr-event-processor",
    },
    "ibkr_order_api": {
        "directory": "ibkr_order_api",
        "repository": "sidechart-ibkr-order-api",
        "function": "sidechart-ibkr-order-api",
    },
}


def run(
    command: list[str],
    *,
    capture_output: bool = False,
    input_text: str | None = None,
) -> str:
    result = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        check=True,
        text=True,
        input=input_text,
        capture_output=capture_output,
    )
    return result.stdout.strip() if capture_output else ""


def aws_region(explicit_region: str | None = None) -> str:
    return (
        explicit_region
        or os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or "us-east-1"
    )


def repository_url(agent_name: str, region: str) -> str:
    account_id = run(
        [
            "aws",
            "sts",
            "get-caller-identity",
            "--query",
            "Account",
            "--output",
            "text",
            "--region",
            region,
        ],
        capture_output=True,
    )
    repository = AGENTS[agent_name]["repository"]
    return f"{account_id}.dkr.ecr.{region}.amazonaws.com/{repository}"


def build_image(agent_name: str, image_uri: str) -> None:
    directory = AGENTS[agent_name]["directory"]
    dockerfile = REPOSITORY_ROOT / "backend" / directory / "Dockerfile"
    if not dockerfile.is_file():
        raise FileNotFoundError(f"Dockerfile not found: {dockerfile}")

    run(
        [
            "docker",
            "build",
            "--platform",
            "linux/amd64",
            "--provenance=false",
            "-f",
            str(dockerfile),
            "-t",
            image_uri,
            str(REPOSITORY_ROOT),
        ]
    )


def ecr_image_exists(image_uri: str, region: str) -> bool:
    """Return whether an immutable image tag is already present in ECR."""
    repository_and_tag = image_uri.split("/", 1)[1]
    repository, tag = repository_and_tag.rsplit(":", 1)
    result = subprocess.run(
        [
            "aws",
            "ecr",
            "describe-images",
            "--repository-name",
            repository,
            "--image-ids",
            f"imageTag={tag}",
            "--region",
            region,
        ],
        cwd=REPOSITORY_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def push_image(image_uri: str, region: str) -> None:
    if ecr_image_exists(image_uri, region):
        print(f"Image already exists in ECR; skipping push: {image_uri}")
        return

    # Terraform can launch multiple image provisioners concurrently. Serialize
    # only the network-heavy push phase to avoid saturating the ECR connection.
    lock_path = Path(tempfile.gettempdir()) / "sidechart-ecr-push.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)

        # Another process may have completed this tag while this one waited.
        if ecr_image_exists(image_uri, region):
            print(f"Image already exists in ECR; skipping push: {image_uri}")
            return

        registry = image_uri.split("/", 1)[0]
        password = run(
            ["aws", "ecr", "get-login-password", "--region", region],
            capture_output=True,
        )
        docker_host = run(
            [
                "docker",
                "context",
                "inspect",
                "--format",
                "{{.Endpoints.docker.Host}}",
            ],
            capture_output=True,
        )
        # Each Terraform provisioner receives an isolated Docker configuration.
        # This prevents concurrent builds from racing over the macOS Keychain.
        with tempfile.TemporaryDirectory(
            prefix="sidechart-docker-config-"
        ) as config_dir:
            docker = ["docker", "--config", config_dir, "--host", docker_host]
            run(
                [
                    *docker,
                    "login",
                    "--username",
                    "AWS",
                    "--password-stdin",
                    registry,
                ],
                input_text=password,
            )

            max_attempts = 5
            for attempt in range(1, max_attempts + 1):
                try:
                    run([*docker, "push", image_uri])
                    return
                except subprocess.CalledProcessError:
                    # A registry timeout can occur after ECR commits the image.
                    if ecr_image_exists(image_uri, region):
                        print(f"ECR committed the image despite timeout: {image_uri}")
                        return
                    if attempt == max_attempts:
                        raise

                    delay_seconds = min(2**attempt, 30)
                    print(
                        f"ECR push attempt {attempt}/{max_attempts} failed; "
                        f"retrying in {delay_seconds}s...",
                        file=sys.stderr,
                    )
                    time.sleep(delay_seconds)


def deploy_image(agent_name: str, image_uri: str, region: str) -> None:
    run(
        [
            "aws",
            "lambda",
            "update-function-code",
            "--function-name",
            AGENTS[agent_name]["function"],
            "--image-uri",
            image_uri,
            "--region",
            region,
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", choices=sorted(AGENTS), required=True)
    parser.add_argument(
        "--tag",
        default=datetime.now(UTC).strftime("manual-%Y%m%d%H%M%S"),
        help="Image tag (defaults to a unique UTC timestamp).",
    )
    parser.add_argument("--region")
    parser.add_argument("--repository-url")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--deploy", action="store_true")
    args = parser.parse_args()

    region = aws_region(args.region)
    repository = args.repository_url
    if (args.push or args.deploy) and not repository:
        repository = repository_url(args.agent, region)
    if not repository:
        repository = AGENTS[args.agent]["repository"]

    image_uri = f"{repository}:{args.tag}"
    print(f"Building {args.agent}: {image_uri}")
    build_image(args.agent, image_uri)

    if args.push or args.deploy:
        push_image(image_uri, region)
        print(f"ECR image ready: {image_uri}")
    if args.deploy:
        deploy_image(args.agent, image_uri, region)
        print(f"Updated {AGENTS[args.agent]['function']}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"Image build failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
