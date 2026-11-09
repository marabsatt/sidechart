#!/usr/bin/env python3
"""Run the deployed integration test for every SideChart Lambda agent."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys

from dotenv import load_dotenv


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPOSITORY_ROOT / "backend"


@dataclass(frozen=True)
class AgentTest:
    name: str
    script: Path


AGENT_TESTS = (
    AgentTest("Planner", BACKEND_DIR / "planner" / "test_full.py"),
    AgentTest("Classifier", BACKEND_DIR / "classifier" / "test_full.py"),
    AgentTest("Reporter", BACKEND_DIR / "reporter" / "test_full.py"),
    AgentTest("Charter", BACKEND_DIR / "charter" / "test_full.py"),
    AgentTest("Sell-side", BACKEND_DIR / "sell_side_agent" / "test_full.py"),
    AgentTest("Supervisor", BACKEND_DIR / "supervisor_agent" / "test_full.py"),
)


def run_agent_test(agent_test: AgentTest, timeout_seconds: int) -> bool:
    """Run one deployed-agent test in an isolated Python process."""
    if not agent_test.script.is_file():
        print(f"  FAIL: test script not found: {agent_test.script}")
        return False

    print(f"\n{'=' * 70}")
    print(f"Testing {agent_test.name}: {agent_test.script.relative_to(REPOSITORY_ROOT)}")
    print("=" * 70, flush=True)

    try:
        result = subprocess.run(
            [sys.executable, str(agent_test.script)],
            cwd=REPOSITORY_ROOT,
            env=os.environ.copy(),
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(
            f"  FAIL: {agent_test.name} exceeded {timeout_seconds} seconds.",
            file=sys.stderr,
        )
        return False

    if result.returncode == 0:
        print(f"  PASS: {agent_test.name}")
        return True

    print(
        f"  FAIL: {agent_test.name} exited with code {result.returncode}.",
        file=sys.stderr,
    )
    return False


def main() -> int:
    """Run every current deployed Lambda integration test."""
    load_dotenv(REPOSITORY_ROOT / ".env", override=True)
    timeout_seconds = int(os.getenv("FULL_TEST_AGENT_TIMEOUT_SECONDS", "1000"))
    if timeout_seconds <= 0:
        print("FULL_TEST_AGENT_TIMEOUT_SECONDS must be positive.", file=sys.stderr)
        return 2

    print("SideChart deployed-agent integration test")
    print(f"Per-agent timeout: {timeout_seconds} seconds")

    results = {
        agent_test.name: run_agent_test(agent_test, timeout_seconds)
        for agent_test in AGENT_TESTS
    }

    print(f"\n{'=' * 70}")
    print("Integration test summary")
    print("=" * 70)
    for name, passed in results.items():
        print(f"  {'PASS' if passed else 'FAIL'}: {name}")

    failed = [name for name, passed in results.items() if not passed]
    if failed:
        print(f"\n{len(failed)} agent test(s) failed: {', '.join(failed)}")
        return 1

    print(f"\nAll {len(results)} deployed-agent tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
