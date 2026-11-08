#!/usr/bin/env python3
"""Build and optionally deploy the supervisor Lambda container image."""

from __future__ import annotations

import argparse
from datetime import datetime, UTC
import os
from pathlib import Path
import subprocess


FUNCTION_NAME = "sidechart-supervisor-agent"
REPOSITORY_NAME = "sidechart-supervisor-agent"
AGENT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = AGENT_DIR.parents[1]


def run(command: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        check=True,
        text=True,
        capture_output=capture,
    )
    return result.stdout.strip() if capture else ""


def build_image(tag: str) -> str:
    image = f"{REPOSITORY_NAME}:{tag}"
    run(
        [
            "docker",
            "build",
            "--platform",
            "linux/amd64",
            "--provenance=false",
            "-f",
            str(AGENT_DIR / "Dockerfile"),
            "-t",
            image,
            str(REPOSITORY_ROOT),
        ]
    )
    return image


def deploy_image(local_image: str, tag: str) -> str:
    account_id = run(
        ["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"],
        capture=True,
    )
    region = (
        os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or "us-east-1"
    )
    registry = f"{account_id}.dkr.ecr.{region}.amazonaws.com"
    repository_uri = f"{registry}/{REPOSITORY_NAME}"
    password = run(
        ["aws", "ecr", "get-login-password", "--region", region], capture=True
    )
    subprocess.run(
        ["docker", "login", "--username", "AWS", "--password-stdin", registry],
        input=password,
        text=True,
        check=True,
    )
    remote_image = f"{repository_uri}:{tag}"
    run(["docker", "tag", local_image, remote_image])
    run(["docker", "push", remote_image])
    run(
        [
            "aws",
            "lambda",
            "update-function-code",
            "--function-name",
            FUNCTION_NAME,
            "--image-uri",
            remote_image,
            "--region",
            region,
        ]
    )
    return remote_image


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deploy", action="store_true")
    args = parser.parse_args()
    tag = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    image = build_image(tag)
    print(f"Built {image}")
    if args.deploy:
        print(f"Deployed {deploy_image(image, tag)}")


if __name__ == "__main__":
    main()
