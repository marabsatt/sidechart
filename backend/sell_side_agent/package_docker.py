#!/usr/bin/env python3
"""Build and optionally deploy the sell-side Lambda container image."""

from pathlib import Path
import subprocess
import sys


BACKEND_DIR = Path(__file__).resolve().parent.parent


if __name__ == "__main__":
    raise SystemExit(
        subprocess.run(
            [
                sys.executable,
                str(BACKEND_DIR / "build_agent_image.py"),
                "--agent",
                "sell_side_agent",
                *sys.argv[1:],
            ],
            cwd=BACKEND_DIR.parent,
            check=False,
        ).returncode
    )
