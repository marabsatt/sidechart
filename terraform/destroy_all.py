#!/usr/bin/env python3
"""Destroy every immediate Terraform stack in reverse dependency order."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys


TERRAFORM_ROOT = Path(__file__).resolve().parent
PREFERRED_ORDER = (
    "frontend",
    "researcher",
    "agents",
    "ingestion",
    "sagemaker",
    "database",
)
FRONTEND_TAGS = {
    "Project": "sidechart",
    "Component": "frontend",
    "ManagedBy": "terraform",
}


def terraform_directories() -> list[Path]:
    """Return immediate child directories containing at least one .tf file."""
    discovered = {
        path.name: path
        for path in TERRAFORM_ROOT.iterdir()
        if path.is_dir() and any(path.glob("*.tf"))
    }
    ordered = [discovered.pop(name) for name in PREFERRED_ORDER if name in discovered]
    ordered.extend(discovered[name] for name in sorted(discovered, reverse=True))
    return ordered


def destroy_command(directory: Path) -> list[str]:
    """Return stack-specific destroy arguments.

    The frontend bucket contains the deployed static site. Terraform's
    force_destroy setting removes those managed objects before deleting the
    bucket, avoiding S3's BucketNotEmpty response.
    """
    command = ["terraform", "destroy", "-auto-approve"]
    if directory.name == "frontend":
        command.append("-var=frontend_bucket_force_destroy=true")
    return command


def run_command(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
    )


def bucket_tags(bucket: str) -> dict[str, str]:
    result = run_command(
        ["aws", "s3api", "get-bucket-tagging", "--bucket", bucket, "--output", "json"]
    )
    if result.returncode != 0:
        return {}
    return {
        item["Key"]: item["Value"]
        for item in json.loads(result.stdout).get("TagSet", [])
    }


def is_managed_frontend_bucket(bucket: str) -> bool:
    tags = bucket_tags(bucket)
    return all(tags.get(key) == value for key, value in FRONTEND_TAGS.items())


def frontend_bucket(directory: Path) -> str | None:
    """Resolve the bucket from state, then safely discover a tagged orphan."""
    output = run_command(
        ["terraform", "output", "-raw", "s3_bucket_name"], cwd=directory
    )
    candidate = output.stdout.strip() if output.returncode == 0 else ""
    if candidate and is_managed_frontend_bucket(candidate):
        return candidate

    result = run_command(
        [
            "aws",
            "s3api",
            "list-buckets",
            "--query",
            "Buckets[?starts_with(Name, 'sidechart-frontend-')].Name",
            "--output",
            "json",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(f"Unable to discover frontend bucket: {result.stderr.strip()}")
    candidates = json.loads(result.stdout)
    managed = [bucket for bucket in candidates if is_managed_frontend_bucket(bucket)]
    if len(managed) > 1:
        raise RuntimeError(
            "Multiple tagged SideChart frontend buckets were found; refusing broad cleanup: "
            + ", ".join(managed)
        )
    return managed[0] if managed else None


def empty_frontend_bucket(bucket: str) -> None:
    """Remove current objects, historical versions, markers, and uploads."""
    print(f"    Emptying managed frontend bucket s3://{bucket} ...", flush=True)
    current = subprocess.run(
        ["aws", "s3", "rm", f"s3://{bucket}", "--recursive"], check=False
    )
    if current.returncode != 0:
        raise RuntimeError(f"Unable to remove current objects from {bucket}")

    versions = run_command(
        ["aws", "s3api", "list-object-versions", "--bucket", bucket, "--output", "json"]
    )
    if versions.returncode != 0:
        raise RuntimeError(f"Unable to list object versions in {bucket}: {versions.stderr.strip()}")
    version_data = json.loads(versions.stdout or "{}")
    objects = [
        {"Key": item["Key"], "VersionId": item["VersionId"]}
        for collection in ("Versions", "DeleteMarkers")
        for item in version_data.get(collection, [])
    ]
    for start in range(0, len(objects), 1000):
        deletion = json.dumps({"Objects": objects[start : start + 1000], "Quiet": True})
        result = run_command(
            [
                "aws", "s3api", "delete-objects", "--bucket", bucket,
                "--delete", deletion, "--output", "json",
            ]
        )
        if result.returncode != 0:
            raise RuntimeError(f"Unable to remove object versions from {bucket}: {result.stderr.strip()}")

    uploads = run_command(
        ["aws", "s3api", "list-multipart-uploads", "--bucket", bucket, "--output", "json"]
    )
    if uploads.returncode != 0:
        raise RuntimeError(f"Unable to list multipart uploads in {bucket}: {uploads.stderr.strip()}")
    for upload in json.loads(uploads.stdout or "{}").get("Uploads", []) or []:
        result = run_command(
            [
                "aws", "s3api", "abort-multipart-upload", "--bucket", bucket,
                "--key", upload["Key"], "--upload-id", upload["UploadId"],
            ]
        )
        if result.returncode != 0:
            raise RuntimeError(f"Unable to abort a multipart upload in {bucket}")


def delete_orphaned_bucket(bucket: str) -> None:
    """Delete the tagged bucket when a failed Terraform destroy lost its state."""
    exists = run_command(["aws", "s3api", "head-bucket", "--bucket", bucket])
    if exists.returncode != 0:
        return
    if not is_managed_frontend_bucket(bucket):
        raise RuntimeError(f"Refusing to delete unverified bucket {bucket}")
    result = run_command(["aws", "s3api", "delete-bucket", "--bucket", bucket])
    if result.returncode != 0:
        raise RuntimeError(f"Unable to delete orphaned bucket {bucket}: {result.stderr.strip()}")
    print(f"    Deleted orphaned managed bucket {bucket}.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Destroy every Terraform subdirectory in reverse dependency order."
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Skip the one-time destroy-all confirmation.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the directory order and commands without running Terraform.",
    )
    args = parser.parse_args()

    if not args.dry_run:
        missing = [name for name in ("terraform", "aws") if shutil.which(name) is None]
        if missing:
            print(f"Error: missing required commands: {', '.join(missing)}.", file=sys.stderr)
            return 1

    directories = terraform_directories()
    if not directories:
        print(f"No Terraform subdirectories found under {TERRAFORM_ROOT}.", file=sys.stderr)
        return 1

    print("Terraform destroy order:")
    for index, directory in enumerate(directories, start=1):
        print(f"  {index}. {directory.name}")

    if not args.dry_run and not args.auto_approve:
        print(
            "\nWARNING: This will destroy all Terraform-managed SideChart infrastructure."
        )
        confirmation = input("Type 'destroy-all' to continue: ").strip()
        if confirmation != "destroy-all":
            print("Destroy cancelled. No Terraform commands were run.")
            return 0

    for directory in directories:
        command = destroy_command(directory)
        print(f"\n==> {directory.name}: {' '.join(command)}", flush=True)
        if args.dry_run:
            if directory.name == "frontend":
                print("    Would empty the verified Terraform-managed frontend bucket first.")
            continue
        bucket = None
        if directory.name == "frontend":
            try:
                bucket = frontend_bucket(directory)
                if bucket:
                    empty_frontend_bucket(bucket)
            except RuntimeError as exc:
                print(f"\nDestroy stopped: {exc}", file=sys.stderr)
                return 1

        result = subprocess.run(command, cwd=directory, check=False)
        if result.returncode != 0:
            print(
                f"\nDestroy stopped: {directory.name} exited with "
                f"status {result.returncode}.",
                file=sys.stderr,
            )
            return result.returncode
        if directory.name == "frontend" and bucket:
            try:
                delete_orphaned_bucket(bucket)
            except RuntimeError as exc:
                print(f"\nDestroy stopped: {exc}", file=sys.stderr)
                return 1

    if args.dry_run:
        print("\nDry run complete. No Terraform commands were run.")
    else:
        print("\nAll Terraform stacks destroyed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
