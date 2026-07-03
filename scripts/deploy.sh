#!/usr/bin/env bash
# Build the Lambda package and deploy the CDK stack in one step.
# Does NOT re-register the Telegram webhook — the Function URL doesn't change
# across deploys, so scripts/set_webhook.py only needs to be run again if the
# stack is destroyed/recreated or the URL otherwise changes.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Building Lambda package..."
uv run python scripts/build_lambda.py

echo "Deploying stack..."
cd infra && cdk deploy

echo "Done."
