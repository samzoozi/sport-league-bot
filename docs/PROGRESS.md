# Implementation Progress

Status snapshot of `@HangarSportBot`, a multi-league Telegram bot for running a volleyball league (squad signup, cost-splitting ledger, per-next-game skip/waitlist replacement, game cards). See `CLAUDE.md` for architecture details.

## Implemented

### Foundation
- Project scaffolded with `uv`, Python 3.13, `python-telegram-bot` (async), `boto3`.
- Local dev runs via long polling (`PYTHONPATH=src uv run python -m bot.local`) against a real dev DynamoDB table (`hangar-sport-bot-dev`, region `ca-central-1`).
- Single DynamoDB table (`db.py`) keyed by a "scope" string — `GROUP#<chat_id>`, or `GROUP#<chat_id>#TOPIC#<thread_id>` when inside a forum topic — for full data isolation between leagues, whether they're separate Telegram groups or separate topics within one forum group.
- `ruff` (lint + format) and `pre-commit` configured; hook installed and passing.
- `scripts/wipe_table.py` — dev-only helper to clear all data from the DynamoDB table for a fresh testing start.
- 38 passing `pytest` tests (`moto`-mocked DynamoDB) covering date/cost math, ledger transactions, registration/waitlist FIFO ordering, skip lifecycle, attendance computation, and scope resolution.

### Group/topic setup & permissions
- `/setupgroup <weekday>` — one-time setup per scope, required before any other command works. In a forum group, this must be run separately in each topic that should act as its own league.
- Admin rights are **not** a bot-managed list — `require_group_admin` checks live via Telegram's `getChatMember` whether the caller is an admin/creator of the group (topic admins aren't a Telegram concept, so this stays chat-level even for topic-scoped leagues).
- No DM flows anywhere; the bot only operates inside group chats and @-tags players when it needs their attention. Outgoing notifications that aren't replies (e.g. waitlist offers) explicitly pass `message_thread_id` so they stay in the correct topic.

### Player registry
- `/register <email> [display name]` — self-service registration (idempotent; re-running updates email/name).
- `/setemail <email>` — update email only.
- `/emails`, `/balance`, `/help`.

### Month lifecycle
- `/newmonth <YYYY-MM> <total_cost> [skip-dates...]` — computes game dates for the group's fixed weekday, posts a signup card with **Join / Decline** inline buttons that edit the card live. Join always succeeds during open signup (uncapped) — capacity is enforced solely at `/finalize`.
- `/squad` — re-post the current open month's signup card.
- `/addplayer` / `/removeplayer` — admin-only, resolve the target via reply-to-message, tap-to-mention picker, or `@username` (only for players who've already interacted with the bot). Intentionally only work on **open** (non-finalized) months — see "Known limitation" below.
- `/deletemonth <YYYY-MM>` — admin-only, deletes an open month's squad. Blocked for finalized months (charges already posted).

### Ledger
- `/finalize [max_players]` — locks the squad (default cap from `MAX_PLAYERS`, sorted by join time; anyone over the cap is simply removed, not waitlisted), splits `total_cost` evenly (`services/months.split_cost`, **truncated** to cents, not rounded — deliberate), and charges each remaining player via an atomic DynamoDB transaction (`db.add_transaction`).
- `/charge`, `/credit`, `/paid`, `/balances` — same target-resolution rules as `/addplayer`.
- All verified live end-to-end, including two real boto3 bugs found and fixed during testing (see `CLAUDE.md` → "Two boto3 client gotchas").

### Skip & waitlist — next-match only
Waitlist and skip are both scoped to the **next match** (`services/months.next_game_date`: the earliest game date `>= today`), not the whole month — see `CLAUDE.md` → "Signup, skip, and waitlist rules" for why.
- `/skip` — only works once a month is finalized; shows a single confirm button for the next match (no picker, since there's only one valid date).
- `/waitlist` — only works once a month is finalized; joins the waitlist for the next match specifically.
- On skip: offers the spot to the first person waitlisted for that date (FIFO), tagging them in-group via a real Telegram mention (`services/mentions.py`, using a `text_mention` entity for players without a public `@username`) with Accept/Decline buttons.
- Accept: marks the skip `replaced`, posts the per-game amount and the original player's e-transfer email so the replacement can pay them directly.
- Decline: cascades the offer to the next waitlisted person for that date; announces an open spot if the waitlist is exhausted or empty.
- **Not yet live-tested end-to-end** (code complete, unit-testable pieces covered by `tests/test_attendance.py` and `tests/test_db.py`, but the full Telegram Accept/Decline button flow with a real waitlisted player has not been exercised in the group yet).

### Game cards
- `/nextgame` — next match's date, confirmed attendees (squad minus open skips, plus any replacements), and a playability status line (`MIN_PLAYERS`/`STANDARD_PLAYERS`/`MAX_PLAYERS` from `config.py`).
- `/games` — full month schedule with per-date confirmed counts (once finalized) or "signups open" (before finalize).

## Remaining

### Finish verifying skip/waitlist
Live-test the full flow in the real group: a squad member skips the next match, the waitlisted player gets tagged with Accept/Decline, and both outcomes (accept → confirmation + e-transfer info; decline → cascades to next waitlisted person or announces an open spot) behave as expected. Also verify the topic-scoped case: two topics in one forum group each running `/setupgroup` independently and staying fully isolated.

### Deployment (not started)
The bot currently only runs via local long polling. Still to build:
- AWS CDK app (Python, per user preference) in `infra/` defining: Lambda function (`python3.13`, `arm64`), a Function URL configured for Telegram's webhook, the production DynamoDB table, and least-privilege IAM grants.
- `src/lambda_function.py` — webhook entry point: verify Telegram's `secret_token` header, then hand the update to the same `python-telegram-bot` `Application` used locally (`bot.app.build_application`).
- `scripts/set_webhook.py` — registers the deployed Function URL (with secret token) as the bot's webhook after `cdk deploy`.
- `cdk bootstrap` (one-time) → `cdk deploy` → run the webhook script → smoke-test by adding the bot to two separate groups and confirming their data stays isolated.

### Known limitation (accepted, not a bug)
`/addplayer`, `/removeplayer`, and `/deletemonth` only work on **open** (non-finalized) months by design — this was an explicit decision because allowing squad edits after `/finalize` would silently desync balances from the actual squad unless every edit also posted a matching charge/refund transaction, which was decided against for now. Post-finalize squad corrections currently have to be handled manually via `/charge`/`/credit`.
