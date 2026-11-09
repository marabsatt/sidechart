#!/usr/bin/env python3
"""Deploy all SideChart Lambda container images through Terraform."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys


TERRAFORM_DIR = Path(__file__).resolve().parent.parent / "terraform" / "agents"


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=TERRAFORM_DIR, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build, push, and deploy all Lambda agent images."
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Pass -auto-approve to terraform apply.",
    )
    args = parser.parse_args()

    if not TERRAFORM_DIR.is_dir():
        print(f"Terraform directory not found: {TERRAFORM_DIR}", file=sys.stderr)
        return 1

    missing = [
        command
        for command in ("terraform", "docker", "aws")
        if not shutil.which(command)
    ]
    if missing:
        print(f"Missing required commands: {', '.join(missing)}", file=sys.stderr)
        return 1

    try:
        run(["terraform", "init"])
        run(["terraform", "validate"])

        # Image builds may run concurrently; the builder serializes ECR pushes.
        command = ["terraform", "apply", "-parallelism=3"]
        if args.auto_approve:
            command.append("-auto-approve")
        run(command)
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"Deployment failed with exit code {exc.returncode}.", file=sys.stderr)
        return exc.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
