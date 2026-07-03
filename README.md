# Hangar Sport Bot

A Telegram bot ([`@HangarSportBot`](https://t.me/HangarSportBot)) for running a volleyball league inside a Telegram group: monthly squad signup, cost-splitting ledger, per-game skip/waitlist replacements, and game-day cards.

One deployment can serve **multiple independent Telegram groups** — each group's squad, waitlist, and balances are fully isolated from every other group. Everything happens inside the group chat; the bot never sends DMs.

## Features

- **Squad signup** — an admin opens a month with `/newmonth`; players join via inline buttons or a waitlist; the admin locks the squad with `/finalize`, which splits the court cost evenly and charges everyone.
- **Balances ledger** — every player has a running balance; admins can post ad-hoc charges/credits and record payments received.
- **Skip & waitlist replacement** — a player can skip a specific game; the bot offers the spot to the next person on the waitlist (tagging them in the group) and shows the replacement who to e-transfer once accepted.
- **Game cards** — `/nextgame` and `/games` show who's actually playing on a given date, accounting for skips and replacements.

Run `/help` in the group for the full, current command list.

## Requirements

- Python 3.13 (managed via [uv](https://docs.astral.sh/uv/))
- A Telegram bot token (create one with [@BotFather](https://t.me/BotFather))
- An AWS account with credentials configured locally (`aws configure` or SSO) — the bot uses DynamoDB for storage

## Setup

```bash
uv sync
```

Create a `.env` file in the project root:

```
BOT_TOKEN=<your bot token>
TABLE_NAME=hangar-sport-bot-dev
AWS_DEFAULT_REGION=<your AWS region>
```

Create the DynamoDB table (once) with a partition key `PK` (String) and sort key `SK` (String), on-demand billing:

```bash
aws dynamodb create-table \
  --table-name hangar-sport-bot-dev \
  --attribute-definitions AttributeName=PK,AttributeType=S AttributeName=SK,AttributeType=S \
  --key-schema AttributeName=PK,KeyType=HASH AttributeName=SK,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --region <your AWS region>
```

## Running locally

```bash
PYTHONPATH=src uv run python -m bot.local
```

This runs the bot via long polling against the real Telegram API. Only one instance can poll at a time — stop any previous instance (`pkill -f "bot.local"`) before starting a new one, and restart after every code change (it doesn't hot-reload).

Add the bot to a Telegram group, then have a group admin run `/setupgroup <weekday>` to get started (e.g. `/setupgroup Monday`).

## Tests

```bash
uv run pytest
```

Tests run against a [`moto`](https://github.com/getmoto/moto)-mocked DynamoDB table and never touch real AWS resources.

## Linting

```bash
uv run ruff check
uv run ruff format
```

A pre-commit hook (`.pre-commit-config.yaml`) runs `ruff check` and `ruff format --check` automatically on every commit.

## Deploying (AWS Lambda, webhook mode)

Infrastructure is defined with [AWS CDK](https://docs.aws.amazon.com/cdk/) (Python) under `infra/`. One-time setup:

```bash
npm install -g aws-cdk
cd infra && cdk bootstrap aws://<account-id>/<region>
```

Then, for every deploy:

```bash
uv run python scripts/build_lambda.py     # bundles dependencies into infra/lambda_build/, no Docker needed
cd infra && cdk deploy
PYTHONPATH=src uv run python scripts/set_webhook.py <function-url-from-deploy-output>
```

`set_webhook.py` registers the deployed Function URL with Telegram and pushes the `/` command menus. Telegram only delivers updates via one mechanism at a time — once a webhook is registered, local long polling (`bot.local`) will start throwing `Conflict` errors (expected; it means the webhook took over). To go back to local dev, delete the webhook first: `curl https://api.telegram.org/bot<token>/deleteWebhook`.

## Project docs

- [`CLAUDE.md`](CLAUDE.md) — architecture notes and conventions for anyone (human or AI) working on this codebase.
- [`docs/PROGRESS.md`](docs/PROGRESS.md) — what's implemented so far and what's still remaining.
