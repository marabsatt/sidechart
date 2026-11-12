#!/usr/bin/env python3
"""Apply every immediate Terraform stack in dependency-aware order."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys


TERRAFORM_ROOT = Path(__file__).resolve().parent
PREFERRED_ORDER = (
    "database",
    "sagemaker",
    "ingestion",
    "agents",
    "researcher",
    "frontend",
)


def terraform_directories() -> list[Path]:
    """Return immediate child directories containing at least one .tf file."""
    discovered = {
        path.name: path
        for path in TERRAFORM_ROOT.iterdir()
        if path.is_dir() and any(path.glob("*.tf"))
    }
    ordered = [discovered.pop(name) for name in PREFERRED_ORDER if name in discovered]
    ordered.extend(discovered[name] for name in sorted(discovered))
    return ordered


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run terraform apply -auto-approve in every Terraform subdirectory."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the directory order and commands without running Terraform.",
    )
    args = parser.parse_args()

    if not args.dry_run and shutil.which("terraform") is None:
        print("Error: terraform is not installed or is not on PATH.", file=sys.stderr)
        return 1

    directories = terraform_directories()
    if not directories:
        print(f"No Terraform subdirectories found under {TERRAFORM_ROOT}.", file=sys.stderr)
        return 1

    command = ["terraform", "apply", "-auto-approve"]
    print("Terraform apply order:")
    for index, directory in enumerate(directories, start=1):
        print(f"  {index}. {directory.name}")

    for directory in directories:
        print(f"\n==> {directory.name}: {' '.join(command)}", flush=True)
        if args.dry_run:
            continue
        result = subprocess.run(command, cwd=directory, check=False)
        if result.returncode != 0:
            print(
                f"\nApply stopped: {directory.name} exited with "
                f"status {result.returncode}.",
                file=sys.stderr,
            )
            return result.returncode

    if args.dry_run:
        print("\nDry run complete. No Terraform commands were run.")
    else:
        print("\nAll Terraform stacks applied successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
