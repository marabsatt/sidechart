#!/usr/bin/env python3
"""Build all SideChart Lambda container images locally."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


BACKEND_DIR = Path(__file__).resolve().parent
BUILD_SCRIPT = BACKEND_DIR / "build_agent_image.py"
AGENTS = (
    "planner",
    "classifier",
    "reporter",
    "charter",
    "sell_side_agent",
    "supervisor_agent",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build all Lambda container images instead of oversized ZIP files."
    )
    parser.add_argument("--tag", default="latest")
    args = parser.parse_args()

    for agent in AGENTS:
        print(f"\nBuilding {agent}...")
        result = subprocess.run(
            [
                sys.executable,
                str(BUILD_SCRIPT),
                "--agent",
                agent,
                "--tag",
                args.tag,
            ],
            cwd=BACKEND_DIR.parent,
            check=False,
        )
        if result.returncode != 0:
            return result.returncode

    print("\nAll Lambda container images built successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
