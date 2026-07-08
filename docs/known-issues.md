# Known issues and improvement ideas

Findings from a critical review of the codebase (2026-07-05), covering bugs,
gaps, and things that can go wrong when this bot is used in a live group chat.

## Fixed

- **Unbound skip-confirm button.** `/skip`'s "Confirm skip" button's
  `callback_data` carried no user id (`skip:pick:{date}`), so any group
  member tapping it — not just whoever ran `/skip` — had the skip applied to
  themselves. Fixed by embedding the requester's user id in the callback data
  and rejecting taps from anyone else, matching the ownership check
  `replace_callback` already had. (`packages/bot/bot/handlers/skips.py`)
- **NaN/Infinity bypassing money validation.** `float()` accepts `"inf"`/
  `"nan"` (case-insensitively), and `nan <= 0` / `inf <= 0` are both `False`,
  so `/newmonth`, `/charge`, `/credit`, `/paid`, `/chargeall`, `/creditall`
  all let non-finite amounts through their `<= 0` guard, corrupting a
  balance or a month's `total_cost`. Fixed via `_parse_positive_amount()` in
  `packages/bot/bot/handlers/admin.py`, which also requires `math.isfinite()`.
- **No timezone awareness.** `next_game_date`/`current_month` compared game
  dates against `date.today()` using the Lambda's server clock (UTC), so a
  game could vanish from "next game" while it was still evening locally, or
  `/skip`/`/addtowaitlist`/offers could stay "valid" for hours after a game
  actually started. Fixed by adding a per-group `timezone` field (`/settimezone`,
  admin-only, a button picker over a small curated list — defaults to UTC
  until set) and `services/months.today_for_scope()`, which every
  `current_month`/`next_game_date` call site now passes explicitly instead of
  relying on the naive default. Still no cutoff *time* within a game day —
  only the date boundary itself is now correct.
- **No idempotency guard on `/finalize`.** It reads the open month, charges
  every player, then flips status to `finalized` as separate, unguarded
  steps. Two concurrent `/finalize` runs (double-tap, two admins racing)
  would both see `status == "open"` and could double-charge the whole squad.
- **No conditional writes on the skip/offer state machine.**
  `set_skip_replaced`/`reopen_skip` are plain unconditional `update_item`
  calls. A slow Lambda response can cause Telegram to retry a webhook
  delivery, processing the same callback twice concurrently with nothing to
  detect it. Related: `/addtowaitlist`'s opportunistic-offer path
  (`player.py`) can send two live Accept/Decline offers for the same spot if
  two people race the "waitlist is empty" check at the same moment.
- **No audit trail for who took a privileged action.** `add_transaction`/
  `add_registration` take `created_by`/`added_by`, but every caller passes a
  hardcoded literal (`"admin"`, `"system"`, `"self"`) instead of the acting
  Telegram user's id/name. In a multi-admin group there's no way to tell
  which admin issued a specific `/charge`, `/credit`, or `/addtosquad`.

## Open — operational gaps

- **No `add_error_handler` registered on the `Application`** (`app.py`). Any
  unhandled exception in a handler is silently logged with no user-facing
  feedback — from the group's perspective the bot just didn't respond.
- **No length cap on `/register`'s display name.** A very long name can push
  `game_card`/`signup_card` text past Telegram's 4096-char message limit,
  with no truncation/chunking anywhere, so that send just fails.
- **No reconciliation when someone leaves the actual Telegram group.** They
  stay fully registered/in the squad and would still get charged at
  `/finalize` with nothing to flag it.
- **`/addplayer`/`/removeplayer` don't reject past game dates.** An admin can
  retroactively edit a game that already happened, including re-triggering a
  "spot is open!" waitlist announcement for a match that's over.

## Open — feature/UX ideas

- Name the specific players cut by `/finalize`'s overflow trimming instead of
  just a count — bumped players currently have no direct notice they were
  dropped.
- Let an admin manually reorder the waitlist queue for edge cases.
- `/balance` is capped at the last 5 transactions with no way to see more.
- Surface "declining removes you from this date's queue entirely" more
  clearly, since re-joining requires manually running `/addtowaitlist` again.
