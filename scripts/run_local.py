#!/usr/bin/env python3
"""Run the SideChart backend and frontend for local development."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


IS_WINDOWS = sys.platform == "win32"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_PORT = 8000
FRONTEND_PORT = 3000
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}"
FRONTEND_URL = f"http://localhost:{FRONTEND_PORT}"
processes: list[subprocess.Popen[str]] = []


def cleanup(signum: int | None = None, frame: object | None = None) -> None:
    """Terminate all subprocesses before exiting."""
    print("\nShutting down services...")
    for proc in processes:
        if proc.poll() is not None:
            continue
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        except Exception:
            proc.kill()
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)


def run_check(command: list[str], cwd: Path | None = None) -> str | None:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            shell=IS_WINDOWS,
            check=False,
        )
    except FileNotFoundError:
        return None
    return result.stdout.strip() or result.stderr.strip()


def check_requirements() -> None:
    checks = {
        "Node.js": run_check(["node", "--version"]),
        "npm": run_check(["npm", "--version"]),
        "uv": run_check(["uv", "--version"]),
    }

    print("\nPrerequisites:")
    missing = []
    for name, version in checks.items():
        if version:
            print(f"  OK {name}: {version}")
        else:
            missing.append(name)
            print(f"  MISSING {name}")

    if missing:
        joined = ", ".join(missing)
        raise SystemExit(f"\nInstall missing tools and rerun: {joined}")


def check_env_files() -> None:
    root_env = PROJECT_ROOT / ".env"
    backend_env = PROJECT_ROOT / "backend" / ".env"
    frontend_env = PROJECT_ROOT / "frontend" / ".env.local"

    print("\nEnvironment files:")
    for path in (root_env, backend_env, frontend_env):
        label = path.relative_to(PROJECT_ROOT)
        if path.exists():
            print(f"  OK {label}")
        else:
            print(f"  optional {label} not found")

    if not root_env.exists() and not backend_env.exists():
        print("  note: backend runs without .env, but chat/data-provider features may need keys")


def ensure_frontend_writable() -> None:
    frontend_dir = PROJECT_ROOT / "frontend"
    next_dir = frontend_dir / ".next"

    if not os.access(frontend_dir, os.W_OK):
        raise SystemExit(
            "\nfrontend/ is not writable. Fix ownership before running local dev:\n"
            '  sudo chown -R "$USER":staff frontend'
        )

    if next_dir.exists() and not os.access(next_dir, os.W_OK):
        raise SystemExit(
            "\nfrontend/.next is not writable. Fix ownership before running local dev:\n"
            '  sudo chown -R "$USER":staff frontend/.next'
        )


def wait_for_url(url: str, timeout_seconds: int) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            request = Request(url, headers={"User-Agent": "sidechart-local-runner"})
            with urlopen(request, timeout=2) as response:
                if 200 <= response.status < 500:
                    return True
        except URLError:
            time.sleep(0.5)
        except TimeoutError:
            time.sleep(0.5)
    return False


def stream_output(proc: subprocess.Popen[str], name: str) -> None:
    if proc.stdout is None:
        return
    for line in proc.stdout:
        print(f"[{name}] {line.rstrip()}")


def start_process(
    name: str,
    command: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.Popen[str]:
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        shell=IS_WINDOWS,
    )
    processes.append(proc)
    threading.Thread(target=stream_output, args=(proc, name), daemon=True).start()
    return proc


def start_backend() -> subprocess.Popen[str]:
    print("\nStarting FastAPI backend...")
    proc = start_process(
        "backend",
        [
            "uv",
            "run",
            "python",
            "-m",
            "uvicorn",
            "backend.server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(BACKEND_PORT),
        ],
        cwd=PROJECT_ROOT,
    )

    if wait_for_url(f"{BACKEND_URL}/health", timeout_seconds=30):
        print(f"Backend running at {BACKEND_URL}")
        print(f"API docs: {BACKEND_URL}/docs")
        return proc

    print("Backend failed to start.")
    cleanup()
    return proc


def start_frontend() -> subprocess.Popen[str]:
    frontend_dir = PROJECT_ROOT / "frontend"
    print("\nStarting Next.js frontend...")

    if not (frontend_dir / "node_modules").exists():
        print("Installing frontend dependencies...")
        subprocess.run(["npm", "install"], cwd=frontend_dir, check=True, shell=IS_WINDOWS)

    env = os.environ.copy()
    env.setdefault("NEXT_PUBLIC_API_BASE_URL", BACKEND_URL)

    proc = start_process(
        "frontend",
        ["npm", "run", "dev", "--", "--hostname", "localhost", "--port", str(FRONTEND_PORT)],
        cwd=frontend_dir,
        env=env,
    )

    if wait_for_url(FRONTEND_URL, timeout_seconds=45):
        print(f"Frontend running at {FRONTEND_URL}")
        return proc

    print("Frontend failed to start.")
    cleanup()
    return proc


def monitor_processes() -> None:
    print("\n" + "=" * 60)
    print("SideChart local development")
    print("=" * 60)
    print(f"Frontend: {FRONTEND_URL}")
    print(f"Backend:  {BACKEND_URL}")
    print(f"API docs: {BACKEND_URL}/docs")
    print("Press Ctrl+C to stop.")
    print("=" * 60 + "\n")

    while True:
        for proc in processes:
            if proc.poll() is not None:
                print("\nA service stopped unexpectedly.")
                cleanup()
        time.sleep(0.5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-checks",
        action="store_true",
        help="Skip prerequisite and environment checks.",
    )
    args = parser.parse_args()

    print("SideChart local development setup")
    print("=" * 40)

    if not args.skip_checks:
        check_requirements()
        check_env_files()
        ensure_frontend_writable()

    start_backend()
    start_frontend()
    monitor_processes()


if __name__ == "__main__":
    main()
