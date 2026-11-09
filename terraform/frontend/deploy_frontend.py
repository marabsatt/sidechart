#!/usr/bin/env python3
"""Build and publish the local SideChart frontend for Terraform."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend-dir", type=Path, required=True)
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--long-running-api-base-url", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--distribution-id", required=True)
    parser.add_argument("--region", required=True)
    return parser.parse_args()


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    print(f"Running: {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def find_executable(name: str) -> Path | None:
    """Resolve tools that may be installed through a shell version manager."""
    discovered = shutil.which(name)
    if discovered:
        return Path(discovered)

    if name == "npm":
        nvm_versions = Path.home() / ".nvm" / "versions" / "node"
        candidates = list(nvm_versions.glob("*/bin/npm"))
        if candidates:
            return max(candidates, key=lambda candidate: candidate.stat().st_mtime)

    return None


def main() -> int:
    args = parse_args()
    frontend_dir = args.frontend_dir.resolve()
    package_lock = frontend_dir / "package-lock.json"
    output_dir = frontend_dir / "out"

    if not package_lock.is_file():
        print(f"Missing frontend lock file: {package_lock}", file=sys.stderr)
        return 1
    npm = find_executable("npm")
    aws = find_executable("aws")
    missing = [name for name, path in (("npm", npm), ("aws", aws)) if path is None]
    if missing:
        print(f"Required executable not found: {', '.join(missing)}", file=sys.stderr)
        return 1

    assert npm is not None
    assert aws is not None

    build_env = os.environ.copy()
    build_env["PATH"] = os.pathsep.join(
        [str(npm.parent), build_env.get("PATH", "")]
    ).rstrip(os.pathsep)
    build_env["NEXT_PUBLIC_API_BASE_URL"] = args.api_base_url
    build_env["NEXT_PUBLIC_LONG_RUNNING_API_BASE_URL"] = (
        args.long_running_api_base_url
    )

    try:
        run([str(npm), "ci"], cwd=frontend_dir, env=build_env)
        run([str(npm), "run", "build"], cwd=frontend_dir, env=build_env)
        if not (output_dir / "index.html").is_file():
            raise RuntimeError(f"Next.js did not create {output_dir / 'index.html'}")

        destination = f"s3://{args.bucket}"
        run(
            [
                str(aws),
                "s3",
                "sync",
                str(output_dir),
                destination,
                "--delete",
                "--cache-control",
                "no-cache, no-store, must-revalidate",
                "--region",
                args.region,
            ],
            cwd=frontend_dir,
        )

        static_dir = output_dir / "_next" / "static"
        if static_dir.is_dir():
            run(
                [
                    str(aws),
                    "s3",
                    "sync",
                    str(static_dir),
                    f"{destination}/_next/static",
                    "--cache-control",
                    "public, max-age=31536000, immutable",
                    "--region",
                    args.region,
                ],
                cwd=frontend_dir,
            )

        run(
            [
                str(aws),
                "cloudfront",
                "create-invalidation",
                "--distribution-id",
                args.distribution_id,
                "--paths",
                "/*",
            ],
            cwd=frontend_dir,
        )
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"Frontend deployment failed: {exc}", file=sys.stderr)
        return 1

    print(f"Frontend deployed to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
