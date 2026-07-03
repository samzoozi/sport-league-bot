#!/usr/bin/env python3
"""Build the Lambda deployment package into infra/lambda_build/.

All three runtime dependencies (python-telegram-bot, boto3, python-dotenv)
and their full transitive dependency trees are pure Python — no C
extensions — so a plain dependency install works regardless of host
OS/architecture. No Docker/cross-compilation needed. Keep the package list
below in sync with pyproject.toml's [project.dependencies].

Run this before every `cdk deploy`:
    uv run python scripts/build_lambda.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / "infra" / "lambda_build"
DEPENDENCIES = ["python-telegram-bot>=22", "boto3", "python-dotenv"]


def main() -> None:
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True)

    subprocess.run(
        ["uv", "pip", "install", "--target", str(BUILD_DIR), *DEPENDENCIES],
        check=True,
    )

    shutil.copytree(ROOT / "src" / "bot", BUILD_DIR / "bot")
    shutil.copy2(ROOT / "src" / "lambda_function.py", BUILD_DIR / "lambda_function.py")

    print(f"Lambda package built at {BUILD_DIR}")


if __name__ == "__main__":
    sys.exit(main())
