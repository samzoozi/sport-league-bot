# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Telegram bot (`@HangarSportBot`) for running a volleyball league inside a Telegram group: monthly squad signup, cost-splitting ledger, per-game skip/waitlist replacements, and game-day cards. It's built to serve **multiple independent Telegram groups from a single deployment** — every piece of data is scoped by Telegram chat ID, so groups can never see each other's squads or balances.

Everything happens inside the group chat. There are **no DM flows** — when the bot needs a specific player's attention (e.g. offering a waitlist spot), it tags them in the group rather than messaging them privately.

## Commands

```bash
# Install dependencies
uv sync

# Run the bot locally (long polling against the real bot token in .env)
PYTHONPATH=src uv run python -m bot.local

# Run the full test suite
uv run pytest

# Run a single test
uv run pytest tests/test_db.py::test_add_transaction_updates_balance_and_records_txn

# Sanity-check the app wires up without errors (no network calls)
PYTHONPATH=src uv run python -c "from bot.app import build_application; build_application()"
```

Local dev requires `BOT_TOKEN` in `.env` and a real (or moto-mocked, for tests) DynamoDB table named by `TABLE_NAME` (defaults to `hangar-sport-bot-dev`) in the AWS region from your configured AWS credentials/profile. Tests never touch real AWS — `tests/conftest.py` sets fake credentials and spins up a `moto`-mocked table automatically.

Only one instance of `bot.local` can poll Telegram at a time — running a second one causes `telegram.error.Conflict` and neither will reliably process updates. Kill the old process (`pkill -f "bot.local"`) before starting a new one after code changes.

## Architecture

### Single DynamoDB table, partitioned per group

Every item's partition key is `PK = GROUP#<chat_id>`. This is what makes multi-group isolation work: one query against a group's PK (optionally with an `SK begins_with` prefix) retrieves exactly that group's data, and there is no way for one group's handlers to accidentally read another's. Sort keys encode the entity type and its relationships, e.g.:

- `META` — group settings (weekday, title)
- `PLAYER#<user_id>#PROFILE` / `PLAYER#<user_id>#TXN#<ts>` — player profile and ledger entries
- `MONTH#<month>#META` / `MONTH#<month>#REG#<user_id>` / `MONTH#<month>#WL#<ts>#<user_id>` — a month's squad and waitlist (FIFO via timestamp-ordered SK)
- `GAME#<date>#SKIP#<user_id>` — a per-game skip record, with `status` (`open`/`replaced`) and `replacement_id`

All key-building and queries live in `src/bot/db.py` — that's the only file that should construct PK/SK strings directly.

### Two boto3 client gotchas already fixed once (don't reintroduce)

1. **DynamoDB returns numbers as `Decimal`.** Anything read back from the table (e.g. `signup_message_id`) must be cast to `int`/whatever the Telegram API expects before being passed to a `python-telegram-bot` call — `Decimal` isn't JSON-serializable and `edit_message_text(message_id=...)` will fail with a `NetworkError`. `db._normalize_month` handles this for month records; follow that pattern for any new numeric field read out of an item.
2. **`table().meta.client` is not a plain low-level client.** It has the resource layer's auto-serialization hooks attached, so passing it already-typed `{"N": "..."}` values (as `db.add_transaction`'s `transact_write_items` call does) double-wraps them into a `MAP` and DynamoDB rejects the request. Use `db._client()` (a real `boto3.client("dynamodb")`) for any low-level/typed call instead.

### Permissions and gating (`src/bot/services/permissions.py`)

There is no bot-specific admin list. `require_group_admin` checks live, via `get_chat_member`, whether the caller is an `administrator`/`creator` of the Telegram group — admin rights always mirror the group's own Telegram settings. `require_group_setup` blocks every command except `/setupgroup` until a group's `META` item exists. Both decorators also reject DMs via `require_group_chat`.

### Resolving a "target" player from a command

Commands like `/addplayer`, `/charge`, `/credit` need to resolve which player an admin means. `src/bot/services/users.py` supports three ways, in priority order: replying to the player's message, tapping their name from Telegram's mention picker (a `text_mention` entity — the only mechanism that works for players with no public `@username`), or typing a literal `@username` (only works if that player has already interacted with the bot, since a plain `@username` typed by hand carries no entity data for the bot to resolve).

`resolve_target_and_rest` (used by money commands that take extra args like an amount) is the version to use when there are positional arguments *after* the target — it must strip the mention's exact text span (via `entity.offset`/`entity.length`) from the leftover args rather than guessing token counts, since a mentioned display name can be multiple words.

### Money formatting

All currency math funnels through `services/months.split_cost` (total ÷ player count, **truncated** to cents, not rounded — this was an explicit product decision, not a default). Use it rather than re-deriving `Decimal` division/quantize logic inline.

### Message formatting: no `parse_mode`

Nothing in this codebase sets `parse_mode="Markdown"`/`"HTML"`. Player names and free-text descriptions flow into card/help text, and Telegram's Markdown parser throws a hard `BadRequest` on any unmatched `_`/`*` — a single player with an underscore in their name would crash every message that mentions them. Keep new user-facing text as plain strings. Mentioning a specific user should go through `services/mentions.mention_text_and_entities`, which uses a `text_mention` `MessageEntity` instead of markup.

### Handler/service layout

- `handlers/` — one file per command group (`setup`, `player`, `admin`, `signup` callbacks, `skips` callbacks), thin: parse args, call `db`/`services`, reply.
- `services/` — business logic with no Telegram-specific I/O beyond what's passed in: `months` (date math, cost split), `permissions`, `users` (mention resolution), `mentions` (mention formatting), `cards` (message text formatting), `attendance` (who's actually playing a given date, accounting for skips/replacements).
- `app.py` builds the `Application`, registers every handler, and pushes two separate Telegram command menus via `set_my_commands` — one scoped to all group chats (player commands) and one scoped to chat administrators (adds the admin commands on top).

### Deployment status

Not yet deployed. The plan is AWS Lambda behind a Function URL (webhook mode) with infrastructure defined via AWS CDK (Python) — this has not been built yet; local dev currently only runs via long polling (`bot.local`).
