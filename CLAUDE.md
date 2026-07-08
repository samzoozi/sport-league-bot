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
uv run python -m bot.local

# Run the full test suite
uv run pytest

# Run a single test
uv run pytest tests/test_db.py::test_add_transaction_updates_balance_and_records_txn

# Sanity-check the app wires up without errors (no network calls)
uv run python -c "from bot.app import build_application; build_application()"
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
- `GAME#<date>#EXTRA#<user_id>` — an admin-added "guest" attendee for one specific game, independent of any registration or skip (see `/addplayer` below)

All key-building and queries live in `packages/bot/bot/db.py` — that's the only file that should construct PK/SK strings directly.

### Scoping: groups vs. forum topics (`packages/bot/bot/services/scope.py`)

Telegram's "forum" groups can have multiple topics (e.g. "Monday Games", "Wednesday Games") that all share one chat ID. `resolve_scope(update)` is the single source of truth for turning an update into a DynamoDB scope string: it returns `GROUP#<chat_id>#TOPIC#<message_thread_id>` when `update.effective_message.is_topic_message` is true (a genuine topic message), and plain `GROUP#<chat_id>` otherwise — which covers ordinary groups *and* a forum's implicit "General" thread, so those behave exactly like a non-forum group. `topic_thread_id(update)` returns the thread ID to pass to outgoing Bot API calls (or `None`), for the one case that needs it — see below.

Every handler calls `resolve_scope(update)` once and passes the result to `db.*` calls; it keeps `update.effective_chat.id` separately for any actual Telegram Bot API call (`send_message`, `get_chat_member`, `edit_message_text`, `delete_message`), since those are always chat-scoped, never topic-scoped, by Telegram's own API. `/setupgroup` must be run once per scope — running it in "Monday Games" does not set up "Wednesday Games", by design.

Replies (`update.effective_message.reply_text(...)`) auto-thread into the correct topic because Telegram threads a reply based on the message being replied to — no extra work needed. Fire-and-forget notifications that aren't replies (`bot.send_message(chat_id, ...)`, used by `handlers/skips.py`'s waitlist-offer messages) do **not** auto-thread and must pass `message_thread_id=topic_thread_id(update)` explicitly, or they'll land in "General" regardless of which topic triggered them.

### Two boto3 client gotchas already fixed once (don't reintroduce)

1. **DynamoDB returns numbers as `Decimal`.** Anything read back from the table (e.g. `signup_message_id`) must be cast to `int`/whatever the Telegram API expects before being passed to a `python-telegram-bot` call — `Decimal` isn't JSON-serializable and `edit_message_text(message_id=...)` will fail with a `NetworkError`. `db._normalize_month` handles this for month records; follow that pattern for any new numeric field read out of an item.
2. **`table().meta.client` is not a plain low-level client.** It has the resource layer's auto-serialization hooks attached, so passing it already-typed `{"N": "..."}` values (as `db.add_transaction`'s `transact_write_items` call does) double-wraps them into a `MAP` and DynamoDB rejects the request. Use `db._client()` (a real `boto3.client("dynamodb")`) for any low-level/typed call instead.

### Signup, skip, and waitlist rules

These aren't arbitrary — they're explicit product decisions, not something to "simplify" back to the obvious generic design:

- **Pre-finalize (open signup):** only Join / Decline. No self-serve waitlist during signup — `/finalize` is the only capacity enforcement, sorting registrations by join time and dropping anyone past `MAX_PLAYERS` (no waitlist placement for them either — they're just removed).
- **Post-finalize:** `/addtowaitlist`, `/leavewaitlist`, and `/skip` all only ever apply to the **next match** — the earliest game date in the month that hasn't happened yet (`services/months.next_game_date`). There's no "waitlist for the whole month" or "skip any future date" — a player waitlisted for one date isn't automatically in line for a later one, and rolls over to the following date for free the day after a match happens (since `next_game_date` just filters `game_date >= today`, no explicit rollover step needed). `/waitlist` (no `add`/`leave`) is the read-only counterpart — it just lists who's currently queued for the next match, and doesn't require the caller to be registered, matching `/nextgame`/`/games`.
- This is why the waitlist DynamoDB key (`GAME#<date>#WL#...`) mirrors the skip key (`GAME#<date>#SKIP#...`) rather than being month-scoped — both are inherently per-game concepts now.
- **`/addtowaitlist` is opportunistic when the queue is empty.** If a skip for that date is still `status == "open"` (nobody was waiting, or everyone offered so far declined) and this is the first person to hit `/addtowaitlist` since then, `handlers/player.py`'s `addtowaitlist()` skips the queue entirely and calls `handlers/skips.py`'s `offer_next` directly, sending them the same Accept/Decline card a queued candidate would get — instead of silently registering them behind a queue that no longer exists. This only fires when the waitlist was empty *before* they joined; if someone's already queued (even mid-offer, since a skip stays `"open"` until actually accepted), a new joiner just falls in behind them as normal, since a pending offer for the front-of-queue candidate could otherwise get double-offered.
- **A registrant who has skipped the next match can also use `/addtowaitlist`** to take a *different* open spot instead. `is_registered` alone no longer blocks the command — the "already in the squad" block only fires if they haven't skipped (`db.get_skip(...) is None`). `attendees_for_date` already correctly excludes a skipped registrant from "currently playing," so no separate eligibility check was needed beyond narrowing that one condition. A registrant can even end up as their own replacement this way (if their own still-open skip happens to be the one offered back to them) — `services/cards.game_card` collapses that case to a plain `✅ Name` instead of a confusing `Name → Name`.
- **A replacement who accepted a skipped spot can back out too, and this chains indefinitely.** `/skip`'s eligibility is "are you actually confirmed to play the next match" (`services/attendance.attendees_for_date`), not "are you in the month's squad" (`db.is_registered`) — so it works both for an original registrant *and* whoever's currently holding their spot via a replacement. A skip record is keyed by the **original registrant's** user_id for its entire lifetime — vacating and re-filling it just overwrites `replacement_id` (already true before this) and a `vacated_by` field (whoever most recently backed out, used only for the "❌ *X* can't play" announcement text). Because of that, `attendees_for_date` needed zero changes to support chains: it already reads `replacement_id` when `status == "replaced"` and nothing when `status == "open"`, so it reflects the current holder no matter how many hops occurred. `db.get_occupied_skip` is the reverse lookup (find the record whose `replacement_id` is a given non-registered user) that lets a replacement's `/skip` find "whose slot am I vacating." **Payment always stays attributed to the original registrant** — `replace_callback`'s "please e-transfer to {skipper}" message and every `callback_data` reference the record's owner_id, never the display-only `vacated_by` identity — since the original registrant is who was actually charged at `/finalize`, regardless of how many replacements the spot has churned through since.
- **Multiple months can coexist**, e.g. a coordinator finalizes next month's squad while this month's games are still being played. `/nextgame`, `/skip`, `/waitlist`/`/addtowaitlist`/`/leavewaitlist`, and `/games` don't use "whichever month was created most recently" — they use `services/months.current_month`, which picks the *finalized* month with the earliest still-upcoming game date (falling back to the most recently created month only if no finalized month has any upcoming date left). Don't reintroduce a plain "pick the max month key" shortcut here (that was `db.get_latest_month`, since removed) — it silently jumps to a newer month before the current one's games are actually done.

### Post-finalize per-game admin overrides (`/addplayer`, `/removeplayer`)

Distinct from `/addtosquad`/`/removefromsquad` (which only work pre-finalize, editing the whole month's squad) — `/addplayer` and `/removeplayer` are admin-only, **post-finalize only**, and scoped to **one specific game date**, not the whole month. Usage mirrors the money commands: reply-to-message/mention-picker/`@username` (via `resolve_target_and_rest`) followed by the date, e.g. `/addplayer @user 2026-08-10`. `services/months.month_for_date` resolves which month owns an arbitrary date — unlike `current_month`, it isn't restricted to "whichever month owns the next upcoming game"; it works for any date in any month regardless of status, and the handlers explicitly reject a date whose month isn't finalized yet.

These were deliberately kept simple rather than integrated into the skip/waitlist machinery — confirmed product decisions, not gaps to "fix":

- **They never touch balances.** Every reply includes an explicit warning that the admin must run `/charge`/`/credit` manually if money needs to move. Auto-adjusting the ledger (e.g. recomputing `cost_per_player` across a changed headcount) was considered and explicitly rejected as over-engineering for this bot's scale.
- **`/removeplayer` does offer the vacated spot to the waitlist**, same as `/skip` — after marking the spot open, it calls the same `offer_next` function `/skip` uses, so whoever's next on the waitlist gets an Accept/Decline offer (or, if the waitlist's empty, the same "spot is open" announcement). This was originally a silent removal with no waitlist offer, but that left a vacated spot with no path to ever getting filled unless someone happened to run `/addtowaitlist` while the queue was momentarily empty — changed after that gap was identified as a real bug, not a deliberate simplification worth keeping.
- **`/addplayer` can add a "guest" beyond the normal squad**, even when nobody has an open/unfilled skip for that date — a new `GAME#<date>#EXTRA#<user_id>` record (`db.add_extra_attendee`/`list_extra_attendees`), independent of any registration. `services/attendance.game_roster` folds these in alongside registrants so `attendees_for_date` picks them up automatically, with no changes needed to callers. Removing a guest via `/removeplayer` is unaffected by the waitlist-offer change above — there's no squad spot to vacate, just an erased extra record.
- **A registrant removed via `/removeplayer` (who hadn't already skipped) is implemented as a plain `db.add_skip`** — the exact same mechanism as a self-service `/skip`. This means they still show up on `/nextgame` as `❌ Name (no replacement yet)` until the waitlist offer above is accepted, identical to a genuine self-skip, rather than disappearing from the roster entirely. Confirmed as the desired behavior — don't introduce a separate hidden/removed marker to make them vanish unless explicitly asked again.

### Permissions and gating (`packages/bot/bot/services/permissions.py`)

There is no bot-specific admin list. `require_group_admin` checks live, via `get_chat_member`, whether the caller is an `administrator`/`creator` of the Telegram group — admin rights always mirror the group's own Telegram settings. `require_group_setup` blocks every command except `/setupgroup` until a group's `META` item exists. Both decorators also reject DMs via `require_group_chat`.

Separately, **which groups the bot can be added to at all** is controlled by `ALLOWED_CHAT_IDS` (`config.py`), a comma-separated list of chat IDs. Telegram itself has no invite-time whitelist for bots, so this is enforced reactively: `handlers/setup.guard_chat_membership` is registered in `app.py` as a `ChatMemberHandler(..., ChatMemberHandler.MY_CHAT_MEMBER)`, and fires whenever the bot's own membership status changes. When it detects the bot just joined a group (`old_chat_member.status` transitioning from `left`/`banned` to `member`/`administrator`) whose chat ID isn't in the allowlist, it posts a short explanation and calls `bot.leave_chat`. Leaving `ALLOWED_CHAT_IDS` unset (the default, including local dev) disables the check entirely — same env-var-with-sane-default pattern as `MIN_PLAYERS`/etc. Private chats are explicitly excluded from the check (the bot has no DM flows and `my_chat_member` also fires there when a user blocks/unblocks it in DM). `infra/stacks/bot_stack.py` reads `ALLOWED_CHAT_IDS` from `os.environ`, same as `BOT_TOKEN`/`WEBHOOK_SECRET_TOKEN` — set it in the local `.env` (loaded by `infra/app.py`'s `load_dotenv` call), and it passes through to the Lambda's environment only if set. Chat IDs aren't secret the way a bot token is, but they do identify which real Telegram groups use this deployment, so — unlike the CDK feature-flag values in `infra/cdk.json`'s committed `context` block — they're kept in `.env` (gitignored) instead, so a fresh clone never has real group IDs sitting in git history going forward.

### Resolving a "target" player from a command

Commands like `/addtosquad`, `/charge`, `/credit` need to resolve which player an admin means. `packages/bot/bot/services/users.py` supports three ways, in priority order: replying to the player's message, tapping their name from Telegram's mention picker (a `text_mention` entity — the only mechanism that works for players with no public `@username`), or typing a literal `@username` (only works if that player has already interacted with the bot, since a plain `@username` typed by hand carries no entity data for the bot to resolve).

`resolve_target_and_rest` (used by money commands that take extra args like an amount, and by `/addplayer`/`/removeplayer`'s trailing game date) is the version to use when there are positional arguments *after* the target — it must strip the mention's exact text span (via `entity.offset`/`entity.length`) from the leftover args rather than guessing token counts, since a mentioned display name can be multiple words.

### Money formatting

All currency math funnels through `services/months.split_cost` (total ÷ player count, **truncated** to cents, not rounded — this was an explicit product decision, not a default). Use it rather than re-deriving `Decimal` division/quantize logic inline.

### Message formatting: no `parse_mode`

Nothing in this codebase sets `parse_mode="Markdown"`/`"HTML"`. Player names and free-text descriptions flow into card/help text, and Telegram's Markdown parser throws a hard `BadRequest` on any unmatched `_`/`*` — a single player with an underscore in their name would crash every message that mentions them. Keep new user-facing text as plain strings. Mentioning a specific user should go through `services/mentions.mention_text_and_entities`, which uses a `text_mention` `MessageEntity` instead of markup.

### Handler/service layout

- `handlers/` — one file per command group (`setup`, `player`, `admin`, `signup` callbacks, `skips` callbacks), thin: parse args, call `db`/`services`, reply.
- `services/` — business logic with no Telegram-specific I/O beyond what's passed in: `months` (date math, cost split, `current_month`/`month_for_date` for resolving which month a game date belongs to), `permissions`, `scope` (group/topic scope resolution), `users` (mention resolution), `mentions` (mention formatting), `cards` (message text formatting, including the full per-game roster with ✅/❌ markers), `attendance` (`attendees_for_date`/`game_roster` — who's actually playing a given date, accounting for skips/replacements/extra attendees).
- `app.py` builds the `Application`, registers every handler, and (via `set_bot_commands`) pushes two separate Telegram command menus via `set_my_commands` — one scoped to all group chats (player commands) and one scoped to chat administrators (adds the admin commands on top). `set_bot_commands` is only invoked automatically by `run_polling()`'s `post_init` hook — it does **not** run for plain `Application.initialize()` (what the Lambda handler uses), so `scripts/set_webhook.py` calls it explicitly once after every deploy. Don't assume it fires in production without that script having been run.

### Dev vs. prod config for `MIN_PLAYERS`/`STANDARD_PLAYERS`/`MAX_PLAYERS`

`config.py` reads these from env vars with the real values (10/12/14) baked in as defaults. Local `.env` intentionally overrides them lower for testing (so exercising "squad full"/waitlist/overflow doesn't require a real 14-person squad) — this is deliberate, not a bug to "fix" by removing the overrides. When the CDK stack is built, do **not** copy these into the Lambda's environment variables — leaving them unset in production is what makes it pick up the real defaults automatically. This env-var-with-sane-default pattern is the general approach for any other dev/prod config split too; it doesn't need a second config file.

### Deployment (AWS Lambda, webhook mode)

- `infra/` — CDK app in Python (`app.py` entrypoint, `stacks/bot_stack.py`). Defines the production DynamoDB table (`hangar-sport-bot`, `RemovalPolicy.RETAIN`), a `python3.13`/`arm64` Lambda, a public Function URL (`FunctionUrlAuthType.NONE` — Telegram calls it directly, no AWS SigV4 available; security is entirely the secret-token header check in the handler), and IAM grants. `table.grant_read_write_data(fn)` does **not** include `TransactWriteItems`/`TransactGetItems` — those are granted explicitly, since `db.add_transaction` (every ledger command) depends on them. Forgetting this grant breaks `/finalize`, `/charge`, etc. in prod with a silent `AccessDenied`.
- `packages/lambda_handler/lambda_function.py` — the webhook entry point, a real uv workspace package (`lambda-handler`, its own `pyproject.toml`) rather than a loose file. Verifies the `X-Telegram-Bot-Api-Secret-Token` header against `WEBHOOK_SECRET_TOKEN`, then processes the update via `async with application:` (the same `Application` from `bot.app.build_application`, built once at module scope) — this is PTB's own recommended pattern for serverless: `initialize()`/`shutdown()` once per invocation rather than trying to persist an event loop across warm Lambda invocations.
- The bot's own code (`packages/bot/`, package name `sport-league-bot`, importable as `bot`) is a `uv` workspace member just like `packages/lambda_handler` — the root `pyproject.toml` has no `[project]` table of its own; it's a "virtual" workspace root that just declares `[tool.uv.workspace] members = ["packages/*"]` plus the shared `dev`/`infra` dependency groups. `packages/lambda_handler` depends on the bot package via `[tool.uv.sources] sport-league-bot = { workspace = true }`. This is what lets `lambda-handler` declare its own real dependency list (`sport-league-bot`, `boto3`, `python-telegram-bot`, `python-dotenv`) instead of a hand-maintained copy of `packages/bot`'s deps — the two can never drift out of sync since there's only one list now, resolved from the shared `uv.lock`.
- `scripts/build_lambda.py` — builds the deployment package into `infra/lambda_build/` (gitignored) by running `uv sync --package lambda-handler --frozen --no-dev --no-editable --compile-bytecode` into an isolated venv (`infra/lambda_venv/`, gitignored, also cleaned before each run), then copying that venv's `site-packages` wholesale into `infra/lambda_build/`. `UV_PROJECT_ENVIRONMENT` is overridden to point `uv sync` at that isolated venv — without it, `uv sync --package` targets the real shared `.venv/` (used for pytest/ruff/local dev) and would strip it down to just the Lambda's minimal runtime deps. `--no-editable` is required so the workspace member (`sport-league-bot`) lands as real copied files rather than an editable path reference back to `packages/bot/bot/`, which would be useless once copied elsewhere. No Docker needed — every dependency here is pure Python. Run this before every `cdk deploy`; if in doubt whether the real dev venv got touched, just run a plain `uv sync` afterward to restore it.
- `scripts/set_webhook.py` — registers the deployed Function URL with Telegram (with the secret token) and calls `set_bot_commands` (see above).
- CDK's own dependencies (`aws-cdk-lib`, `constructs`) live in a separate `infra` `uv` dependency group (`uv run --group infra ...`), not in either runtime package's dependencies — keeps the Lambda package from being bloated with deployment tooling.
- Deploy flow: `cdk bootstrap` (one-time per account/region) → `uv run python scripts/build_lambda.py` → `cd infra && cdk deploy` → `uv run python scripts/set_webhook.py <function-url-from-deploy-output>`. After the first deploy, `scripts/deploy.sh` collapses the build+deploy steps into one command (`./scripts/deploy.sh`) — it doesn't re-run `set_webhook.py`, since the Function URL doesn't change across ordinary deploys.
- Telegram only delivers updates via one mechanism at a time — once a webhook is registered, local long-polling (`bot.local`) will start throwing `Conflict` errors. That's expected, not a bug; it means the webhook took over. `scripts/go_local.sh` / `scripts/go_prod.sh` automate the full switch (delete-webhook-and-run vs. stop-and-reregister) — use those instead of doing it by hand.
