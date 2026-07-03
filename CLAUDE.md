# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Telegram bot (`@HangarSportBot`) for running a volleyball league inside a Telegram group: monthly squad signup, cost-splitting ledger, per-game skip/waitlist replacements, and game-day cards. It's built to serve **multiple independent leagues from a single deployment** — every piece of data is scoped by Telegram chat ID (and, inside a forum group, by topic — see "Scoping" below), so groups/topics can never see each other's squads or balances.

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

### Single DynamoDB table, partitioned per scope

Every item's partition key is a "scope" string: `GROUP#<chat_id>`, or `GROUP#<chat_id>#TOPIC#<message_thread_id>` when the update came from inside a genuine forum topic (see "Scoping" below). This is what makes group/topic isolation work: one query against a scope's PK (optionally with an `SK begins_with` prefix) retrieves exactly that scope's data, and there is no way for one group's (or topic's) handlers to accidentally read another's. Every `db.py` function takes this pre-resolved scope string as its first argument — `db.py` itself never computes it. Sort keys encode the entity type and its relationships, e.g.:

- `META` — group settings (weekday, title)
- `PLAYER#<user_id>#PROFILE` / `PLAYER#<user_id>#TXN#<ts>` — player profile and ledger entries
- `MONTH#<month>#META` / `MONTH#<month>#REG#<user_id>` — a month's squad
- `GAME#<date>#SKIP#<user_id>` — a per-game skip record, with `status` (`open`/`replaced`) and `replacement_id`
- `GAME#<date>#WL#<ts>#<user_id>` — waitlist entry for one specific game date (FIFO via timestamp-ordered SK) — see "Signup, skip, and waitlist rules" below for why this is per-date, not per-month

All key-building and queries live in `src/bot/db.py` — that's the only file that should construct PK/SK strings directly.

### Scoping: groups vs. forum topics (`src/bot/services/scope.py`)

Telegram's "forum" groups can have multiple topics (e.g. "Monday Games", "Wednesday Games") that all share one chat ID. `resolve_scope(update)` is the single source of truth for turning an update into a DynamoDB scope string: it returns `GROUP#<chat_id>#TOPIC#<message_thread_id>` when `update.effective_message.is_topic_message` is true (a genuine topic message), and plain `GROUP#<chat_id>` otherwise — which covers ordinary groups *and* a forum's implicit "General" thread, so those behave exactly like a non-forum group. `topic_thread_id(update)` returns the thread ID to pass to outgoing Bot API calls (or `None`), for the one case that needs it — see below.

Every handler calls `resolve_scope(update)` once and passes the result to `db.*` calls; it keeps `update.effective_chat.id` separately for any actual Telegram Bot API call (`send_message`, `get_chat_member`, `edit_message_text`, `delete_message`), since those are always chat-scoped, never topic-scoped, by Telegram's own API. `/setupgroup` must be run once per scope — running it in "Monday Games" does not set up "Wednesday Games", by design.

Replies (`update.effective_message.reply_text(...)`) auto-thread into the correct topic because Telegram threads a reply based on the message being replied to — no extra work needed. Fire-and-forget notifications that aren't replies (`bot.send_message(chat_id, ...)`, used by `handlers/skips.py`'s waitlist-offer messages) do **not** auto-thread and must pass `message_thread_id=topic_thread_id(update)` explicitly, or they'll land in "General" regardless of which topic triggered them.

### Two boto3 client gotchas already fixed once (don't reintroduce)

1. **DynamoDB returns numbers as `Decimal`.** Anything read back from the table (e.g. `signup_message_id`) must be cast to `int`/whatever the Telegram API expects before being passed to a `python-telegram-bot` call — `Decimal` isn't JSON-serializable and `edit_message_text(message_id=...)` will fail with a `NetworkError`. `db._normalize_month` handles this for month records; follow that pattern for any new numeric field read out of an item.
2. **`table().meta.client` is not a plain low-level client.** It has the resource layer's auto-serialization hooks attached, so passing it already-typed `{"N": "..."}` values (as `db.add_transaction`'s `transact_write_items` call does) double-wraps them into a `MAP` and DynamoDB rejects the request. Use `db._client()` (a real `boto3.client("dynamodb")`) for any low-level/typed call instead.

### Signup, skip, and waitlist rules

These aren't arbitrary — they're explicit product decisions, not something to "simplify" back to the obvious generic design:

- **Pre-finalize (open signup):** only Join / Decline. No self-serve waitlist during signup — `/finalize` is the only capacity enforcement, sorting registrations by join time and dropping anyone past `MAX_PLAYERS` (no waitlist placement for them either — they're just removed).
- **Post-finalize:** `/waitlist` and `/skip` both only ever apply to the **next match** — the earliest game date in the month that hasn't happened yet (`services/months.next_game_date`). There's no "waitlist for the whole month" or "skip any future date" — a player waitlisted for one date isn't automatically in line for a later one, and rolls over to the following date for free the day after a match happens (since `next_game_date` just filters `game_date >= today`, no explicit rollover step needed).
- This is why the waitlist DynamoDB key (`GAME#<date>#WL#...`) mirrors the skip key (`GAME#<date>#SKIP#...`) rather than being month-scoped — both are inherently per-game concepts now.

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
- `services/` — business logic with no Telegram-specific I/O beyond what's passed in: `months` (date math, cost split), `permissions`, `scope` (group/topic scope resolution), `users` (mention resolution), `mentions` (mention formatting), `cards` (message text formatting), `attendance` (who's actually playing a given date, accounting for skips/replacements).
- `app.py` builds the `Application`, registers every handler, and pushes two separate Telegram command menus via `set_my_commands` — one scoped to all group chats (player commands) and one scoped to chat administrators (adds the admin commands on top).

### Deployment status

Not yet deployed. The plan is AWS Lambda behind a Function URL (webhook mode) with infrastructure defined via AWS CDK (Python) — this has not been built yet; local dev currently only runs via long polling (`bot.local`).
