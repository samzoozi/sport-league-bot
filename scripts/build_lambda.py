#!/usr/bin/env python3
"""Build the Lambda deployment package into infra/lambda_build/.

Uses `uv sync --package lambda-handler` to resolve and install exactly that
workspace package's dependency closure (sport-league-bot, boto3,
python-telegram-bot, python-dotenv — all pure Python, so no Docker/
cross-compilation needed) into an isolated venv, then copies its
site-packages wholesale into infra/lambda_build/.

Run this before every `cdk deploy`:
    uv run python scripts/build_lambda.py
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / "infra" / "lambda_build"
BUILD_VENV = ROOT / "infra" / "lambda_venv"


def main() -> None:
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    if BUILD_VENV.exists():
        shutil.rmtree(BUILD_VENV)

    env = os.environ.copy()
    env["UV_PROJECT_ENVIRONMENT"] = str(BUILD_VENV)

    subprocess.run(
        [
            "uv",
            "sync",
            "--package",
            "lambda-handler",
            "--frozen",
            "--no-dev",
            "--no-editable",
            "--compile-bytecode",
        ],
        check=True,
        cwd=ROOT,
        env=env,
    )

    site_packages = next(BUILD_VENV.glob("lib/python*/site-packages"))
    shutil.copytree(site_packages, BUILD_DIR)

    print(f"Lambda package built at {BUILD_DIR}")


if __name__ == "__main__":
    sys.exit(main())
