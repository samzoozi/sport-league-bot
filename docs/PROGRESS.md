# Implementation Progress

Status snapshot of `@HangarSportBot`, a multi-league Telegram bot for running a volleyball league (squad signup, cost-splitting ledger, per-next-game skip/waitlist replacement, game cards). See `CLAUDE.md` for architecture details.

## Implemented

### Foundation
- Project scaffolded with `uv`, Python 3.13, `python-telegram-bot` (async), `boto3`.
- Local dev runs via long polling (`PYTHONPATH=src uv run python -m bot.local`) against a real dev DynamoDB table (`hangar-sport-bot-dev`, region `ca-central-1`).
- Single DynamoDB table (`db.py`) keyed by a "scope" string — `GROUP#<chat_id>`, or `GROUP#<chat_id>#TOPIC#<thread_id>` when inside a forum topic — for full data isolation between leagues, whether they're separate Telegram groups or separate topics within one forum group.
- `ruff` (lint + format) and `pre-commit` configured; hook installed and passing.
- `scripts/wipe_table.py` — dev-only helper to clear all data from the DynamoDB table for a fresh testing start. `scripts/delete_month.py` — narrower dev helper that removes just one month's squad/waitlist/skip records, leaving player profiles, balances, and transaction history untouched (unlike `/deletemonth`, works regardless of the month's status).
- 44 passing `pytest` tests (`moto`-mocked DynamoDB) covering date/cost math, ledger transactions, registration/waitlist FIFO ordering (including true join-order, not DynamoDB key order), skip lifecycle, attendance computation, scope resolution, and multi-month "current month" resolution.

### Group/topic setup & permissions
- `/setupgroup` — one-time setup per scope (tap a weekday, or `/setupgroup <weekday>` to skip the buttons), required before any other command works. In a forum group, this must be run separately in each topic that should act as its own league.
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
- **Multiple months can coexist** (e.g. next month's squad gets finalized while this month's games are still being played) — `services/months.current_month` picks whichever finalized month actually owns the next unresolved game, not whichever was created most recently.
- The signup card visibly changes on `/finalize` (locked state, real charged amount, buttons removed) and is re-posted as a fresh, visible message via `post_signup_card` — not just silently edited in place, which could go unnoticed if the original card had scrolled out of view.

### Ledger
- `/finalize [max_players]` — locks the squad (default cap from `MAX_PLAYERS`, sorted by true join order; anyone over the cap is simply removed, not waitlisted), splits `total_cost` evenly (`services/months.split_cost`, **truncated** to cents, not rounded — deliberate), and charges each remaining player via an atomic DynamoDB transaction (`db.add_transaction`).
- `/charge`, `/credit`, `/paid`, `/balances` — same target-resolution rules as `/addplayer`.
- `/chargeall <YYYY-MM> <amount> <desc>` / `/creditall <YYYY-MM> <amount> <desc>` — admin-only, applies the same flat amount to every player registered in that month's squad in one shot.
- All verified live end-to-end, including two real boto3 bugs found and fixed during testing (see `CLAUDE.md` → "Two boto3 client gotchas").

### Skip & waitlist — next-match only
Waitlist and skip are both scoped to the **next match** (`services/months.next_game_date`: the earliest game date `>= today`), not the whole month — see `CLAUDE.md` → "Signup, skip, and waitlist rules" for why.
- `/skip` — only works once a month is finalized; shows a single confirm button for the next match (no picker, since there's only one valid date).
- `/waitlist` — only works once a month is finalized; joins the waitlist for the next match specifically.
- On skip: offers the spot to the first person waitlisted for that date (FIFO), tagging them in-group via a real Telegram mention (`services/mentions.py`, using a `text_mention` entity for players without a public `@username`) with Accept/Decline buttons.
- Accept: marks the skip `replaced`, posts the per-game amount and the original player's e-transfer email so the replacement can pay them directly.
- Decline: cascades the offer to the next waitlisted person for that date; announces an open spot if the waitlist is exhausted or empty.
- **Live-tested end-to-end** in the real group, including the full accept flow.

### Game cards
- `/nextgame` — next match's date, confirmed attendees (squad minus open skips, plus any replacements), and a playability status line (`MIN_PLAYERS`/`STANDARD_PLAYERS`/`MAX_PLAYERS` from `config.py`, overridable via env vars for lower-threshold local testing — see `CLAUDE.md`).
- `/games` — full month schedule with per-date confirmed counts (once finalized) or "signups open" (before finalize).

### Deployment (AWS Lambda, webhook mode)
- CDK stack (`infra/`) defines the production DynamoDB table (`hangar-sport-bot`, `RemovalPolicy.RETAIN`), a `python3.13`/`arm64` Lambda behind a public Function URL, and least-privilege IAM (including the explicit `TransactWriteItems`/`TransactGetItems` grant that `grant_read_write_data()` misses).
- `src/lambda_function.py` — webhook handler; verifies the secret-token header, then processes the update via `async with application:` (PTB's own recommended serverless pattern).
- `scripts/build_lambda.py` — Docker-free dependency bundling (every runtime dependency is pure Python, confirmed by inspecting the tree, so a plain `pip install --target` produces a working package regardless of host OS/arch).
- `scripts/set_webhook.py` — registers the deployed Function URL with Telegram and pushes the `/` command menus (which, unlike local polling, don't get set automatically in Lambda's `Application.initialize()` path).
- `cdk synth` verified clean (all expected resources present). Actual `cdk bootstrap`/`deploy` + live smoke test against the deployed Lambda is the one remaining step — see "Remaining" below.

## Remaining

### Finish the deployment
`cdk bootstrap` (one-time) → `scripts/build_lambda.py` → `cdk deploy` → `scripts/set_webhook.py <function-url>` → stop local `bot.local` (Telegram only delivers via one mechanism at a time — a registered webhook will make local polling start throwing `Conflict`, which is expected) → smoke-test the full command set against the deployed Lambda in the real group, checking CloudWatch Logs if anything doesn't respond.

### Known limitation (accepted, not a bug)
`/addplayer`, `/removeplayer`, and `/deletemonth` only work on **open** (non-finalized) months by design — this was an explicit decision because allowing squad edits after `/finalize` would silently desync balances from the actual squad unless every edit also posted a matching charge/refund transaction, which was decided against for now. Post-finalize squad corrections currently have to be handled manually via `/charge`/`/credit`/`/chargeall`/`/creditall`.
