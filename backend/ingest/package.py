"""
Cross-platform Lambda deployment package creator using uv.
Works on Windows, Mac, and Linux.
"""

import os
import subprocess
import sys
import shutil
import tomllib
import zipfile
from pathlib import Path


def install_dependencies(current_dir: Path, package_dir: Path) -> None:
    """Install only this Lambda project's dependencies into the package."""
    project_file = current_dir / "pyproject.toml"
    project = tomllib.loads(project_file.read_text(encoding="utf-8"))
    dependencies = project.get("project", {}).get("dependencies", [])
    if not dependencies:
        return

    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("Could not find uv on PATH; run this script with 'uv run package.py'.")

    subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--python",
            sys.executable,
            "--target",
            str(package_dir),
            "--no-compile",
            *dependencies,
        ],
        cwd=current_dir,
        check=True,
    )
    lock_marker = package_dir / ".lock"
    if lock_marker.exists():
        lock_marker.unlink()


def create_deployment_package():
    """Create a Lambda deployment package with dependencies from uv."""
    
    # Paths
    current_dir = Path(__file__).parent
    build_dir = current_dir / 'build'
    package_dir = build_dir / 'package'
    zip_path = current_dir / 'lambda_function.zip'
    
    # Clean up previous builds
    if build_dir.exists():
        shutil.rmtree(build_dir)
    if zip_path.exists():
        os.remove(zip_path)
    
    # Create build directory
    package_dir.mkdir(parents=True, exist_ok=True)
    
    print("Installing Lambda dependencies from pyproject.toml...")
    install_dependencies(current_dir, package_dir)
    
    # Copy Lambda function code
    print("Copying Lambda function code...")
    
    # Copy S3 Vectors Lambda handlers
    if (current_dir / 'ingest_s3vectors.py').exists():
        shutil.copy(current_dir / 'ingest_s3vectors.py', package_dir)
    if (current_dir / 'search_s3vectors.py').exists():
        shutil.copy(current_dir / 'search_s3vectors.py', package_dir)
    
    # Create ZIP file
    print("Creating deployment package...")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(package_dir):
            # Skip __pycache__ directories
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for file in files:
                if file.endswith('.pyc'):
                    continue
                file_path = Path(root) / file
                arcname = file_path.relative_to(package_dir)
                zipf.write(file_path, arcname)
    
    # Clean up build directory
    shutil.rmtree(build_dir)
    
    # Get file size
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"\n✅ Deployment package created: {zip_path}")
    print(f"   Size: {size_mb:.2f} MB")
    
    if size_mb > 50:
        print("⚠️  Warning: Package exceeds 50MB. Consider using Lambda Layers.")
    
    return str(zip_path)


if __name__ == '__main__':
    create_deployment_package()
