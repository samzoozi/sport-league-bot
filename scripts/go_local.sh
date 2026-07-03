#!/usr/bin/env bash
# Switch from the production webhook to local long polling and start bot.local.
# Deletes the Telegram webhook (production goes offline until go_prod.sh is
# run again), then runs the bot locally against the dev DynamoDB table.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a
source .env
set +a

echo "Deleting webhook (production will be offline until go_prod.sh is run again)..."
curl -s "https://api.telegram.org/bot${BOT_TOKEN}/deleteWebhook" | python3 -m json.tool

echo "Starting local bot (Ctrl+C to stop)..."
PYTHONPATH=src uv run python -m bot.local
