# Implementation Progress

Status snapshot of `@HangarSportBot`, a multi-group Telegram bot for running a volleyball league (squad signup, cost-splitting ledger, per-game skip/waitlist replacement, game cards). See `CLAUDE.md` for architecture details.

## Implemented

### Foundation
- Project scaffolded with `uv`, Python 3.13, `python-telegram-bot` (async), `boto3`.
- Local dev runs via long polling (`PYTHONPATH=src uv run python -m bot.local`) against a real dev DynamoDB table (`hangar-sport-bot-dev`, region `ca-central-1`).
- Single DynamoDB table (`db.py`) keyed by `PK = GROUP#<chat_id>` for full multi-group data isolation — one deployment can serve any number of independent Telegram groups.
- `ruff` (lint + format) and `pre-commit` configured; hook installed and passing.
- 28 passing `pytest` tests (`moto`-mocked DynamoDB) covering date/cost math, ledger transactions, registration/waitlist FIFO ordering, skip lifecycle, and attendance computation.

### Group setup & permissions
- `/setupgroup <weekday>` — one-time setup, required before any other command works in a group.
- Admin rights are **not** a bot-managed list — `require_group_admin` checks live via Telegram's `getChatMember` whether the caller is an admin/creator of that group.
- No DM flows anywhere; the bot only operates inside group chats and @-tags players when it needs their attention.

### Player registry
- `/register <email> [display name]` — self-service registration (idempotent; re-running updates email/name).
- `/setemail <email>` — update email only.
- `/emails`, `/balance`, `/help`.

### Month lifecycle
- `/newmonth <YYYY-MM> <total_cost> [skip-dates...]` — computes game dates for the group's fixed weekday, posts a signup card with **Join / Waitlist / Leave** inline buttons that edit the card live.
- `/squad` — re-post the current open month's signup card.
- `/addplayer` / `/removeplayer` — admin-only, resolve the target via reply-to-message, tap-to-mention picker, or `@username` (only for players who've already interacted with the bot). Intentionally only work on **open** (non-finalized) months — see "Known limitation" below.
- `/deletemonth <YYYY-MM>` — admin-only, deletes an open month's squad/waitlist. Blocked for finalized months (charges already posted).

### Ledger
- `/finalize [max_players]` — locks the squad (default cap from `MAX_PLAYERS`, overflow bumped to waitlist by join order), splits `total_cost` evenly (`services/months.split_cost`, **truncated** to cents, not rounded — deliberate), and charges each player via an atomic DynamoDB transaction (`db.add_transaction`).
- `/charge`, `/credit`, `/paid`, `/balances` — same target-resolution rules as `/addplayer`.
- All verified live end-to-end, including two real boto3 bugs found and fixed during testing (see `CLAUDE.md` → "Two boto3 client gotchas").

### Skip & waitlist replacement flow
- `/skip` — date-picker for a registered player to skip one upcoming game.
- `/waitlist` — join the current month's waitlist directly (in addition to the signup card's Waitlist button).
- On skip: offers the spot to the first waitlisted player (FIFO), tagging them in-group via a real Telegram mention (`services/mentions.py`, using a `text_mention` entity for players without a public `@username`) with Accept/Decline buttons.
- Accept: marks the skip `replaced`, posts the per-game amount and the original player's e-transfer email so the replacement can pay them directly.
- Decline: cascades the offer to the next waitlisted player; announces an open spot if the waitlist is exhausted or empty.
- **Not yet live-tested end-to-end** (code complete, unit-testable pieces covered by `tests/test_attendance.py` and `tests/test_db.py`, but the full Telegram Accept/Decline button flow with a real waitlisted player has not been exercised in the group yet).

### Game cards
- `/nextgame` — next upcoming game's date, confirmed attendees (squad minus open skips, plus any replacements), and a playability status line (`MIN_PLAYERS`/`STANDARD_PLAYERS`/`MAX_PLAYERS` from `config.py`).
- `/games` — full month schedule with per-date confirmed counts (once finalized) or "signups open" (before finalize).

## Remaining

### Finish verifying task 5 (skip/waitlist)
Live-test the full accept/decline replacement flow in the real group: a squad member skips a game, the waitlisted player gets tagged with Accept/Decline, and both outcomes (accept → confirmation + e-transfer info; decline → cascades to next waitlisted person or announces an open spot) behave as expected.

### Deployment (not started)
The bot currently only runs via local long polling. Still to build:
- AWS CDK app (Python, per user preference) in `infra/` defining: Lambda function (`python3.13`, `arm64`), a Function URL configured for Telegram's webhook, the production DynamoDB table, and least-privilege IAM grants.
- `src/lambda_function.py` — webhook entry point: verify Telegram's `secret_token` header, then hand the update to the same `python-telegram-bot` `Application` used locally (`bot.app.build_application`).
- `scripts/set_webhook.py` — registers the deployed Function URL (with secret token) as the bot's webhook after `cdk deploy`.
- `cdk bootstrap` (one-time) → `cdk deploy` → run the webhook script → smoke-test by adding the bot to two separate groups and confirming their data stays isolated.

### Known limitation (accepted, not a bug)
`/addplayer`, `/removeplayer`, and `/deletemonth` only work on **open** (non-finalized) months by design — this was an explicit decision (see conversation history) because allowing squad edits after `/finalize` would silently desync balances from the actual squad unless every edit also posted a matching charge/refund transaction, which was decided against for now. Post-finalize squad corrections currently have to be handled manually via `/charge`/`/credit`.
