#!/usr/bin/env bash
# Switch from local long polling back to the production webhook. Stops any
# running bot.local, looks up the deployed Function URL from the CDK stack,
# and re-registers it as the Telegram webhook.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Stopping local bot..."
pkill -f "bot.local" 2>/dev/null || true

FUNCTION_URL=$(aws cloudformation describe-stacks \
  --stack-name HangarSportBotStack \
  --region ca-central-1 \
  --query "Stacks[0].Outputs[?OutputKey=='FunctionUrl'].OutputValue" \
  --output text)

if [ -z "$FUNCTION_URL" ]; then
  echo "Could not find the deployed Function URL — is the stack deployed?" >&2
  exit 1
fi

echo "Registering webhook: $FUNCTION_URL"
PYTHONPATH=src uv run python scripts/set_webhook.py "$FUNCTION_URL"
