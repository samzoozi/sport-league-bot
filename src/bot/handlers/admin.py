from telegram import Update
from telegram.ext import ContextTypes

from bot import db
from bot.config import MAX_PLAYERS
from bot.handlers.signup import refresh_signup_message
from bot.services.cards import signup_card
from bot.services.months import game_dates_for_month, parse_month, split_cost
from bot.services.permissions import require_group_admin
from bot.services.scope import resolve_scope
from bot.services.users import resolve_target_and_rest, resolve_target_user


@require_group_admin
async def newmonth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if len(args) < 2:
        await update.effective_message.reply_text(
            "Usage: /newmonth <YYYY-MM> <total_cost> [skip-dates YYYY-MM-DD ...]\n"
            "Example: /newmonth 2026-08 240\n"
            "Example with a skipped date: /newmonth 2026-08 240 2026-08-03"
        )
        return

    parsed = parse_month(args[0])
    if parsed is None:
        await update.effective_message.reply_text(
            "Month must look like YYYY-MM, e.g. 2026-08."
        )
        return

    try:
        total_cost = float(args[1])
        if total_cost <= 0:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text(
            "Total cost must be a positive number."
        )
        return

    month_key = args[0]
    scope = resolve_scope(update)

    if db.get_month(scope, month_key) is not None:
        await update.effective_message.reply_text(
            f"{month_key} already has a squad set up."
        )
        return

    year, month_num = parsed
    group = db.get_group(scope)
    weekday = group["weekday"]
    weekday_index = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ].index(weekday)
    skip_dates = set(args[2:])
    game_dates = game_dates_for_month(year, month_num, weekday_index, skip_dates)
    if not game_dates:
        await update.effective_message.reply_text(
            f"No {weekday}s left in {month_key} after excluding the skip dates."
        )
        return

    db.create_month(scope, month_key, weekday, game_dates, total_cost)

    text, keyboard = signup_card(db.get_month(scope, month_key), [], {})
    message = await update.effective_message.reply_text(text, reply_markup=keyboard)
    db.set_month_signup_message(scope, month_key, message.message_id)


@require_group_admin
async def deletemonth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("Usage: /deletemonth <YYYY-MM>")
        return

    month_key = context.args[0]
    chat_id = update.effective_chat.id
    scope = resolve_scope(update)
    month_meta = db.get_month(scope, month_key)
    if month_meta is None:
        await update.effective_message.reply_text(f"No month found for {month_key}.")
        return

    if month_meta["status"] != "open":
        await update.effective_message.reply_text(
            f"{month_key} has already been finalized and can't be deleted "
            "(charges have already been posted). Use /credit to reverse charges if needed."
        )
        return

    signup_message_id = month_meta.get("signup_message_id")
    db.delete_month(scope, month_key)

    if signup_message_id:
        try:
            await context.bot.delete_message(chat_id, signup_message_id)
        except Exception:
            pass

    await update.effective_message.reply_text(f"Deleted {month_key} and its signups.")


@require_group_admin
async def addplayer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    scope = resolve_scope(update)
    target = resolve_target_user(update, context)
    if target is None:
        await update.effective_message.reply_text(
            "Reply to their message with /addplayer, or run /addplayer @username "
            "for someone who has already registered."
        )
        return

    month_meta = db.get_open_month(scope)
    if month_meta is None:
        await update.effective_message.reply_text(
            "No open month right now — run /newmonth first."
        )
        return

    month = month_meta["month"]
    db.ensure_player_stub(scope, target["user_id"], target["name"], target["username"])

    if db.is_registered(scope, month, target["user_id"]):
        await update.effective_message.reply_text(
            f"{target['name']} is already in the squad."
        )
        return

    db.remove_waitlist_entry(scope, month, target["user_id"])
    db.add_registration(scope, month, target["user_id"], added_by="admin")
    await update.effective_message.reply_text(f"Added {target['name']} to the squad.")
    await refresh_signup_message(context.bot, scope, chat_id, month)


@require_group_admin
async def removeplayer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    scope = resolve_scope(update)
    target = resolve_target_user(update, context)
    if target is None:
        await update.effective_message.reply_text(
            "Reply to their message with /removeplayer, or run /removeplayer @username."
        )
        return

    month_meta = db.get_open_month(scope)
    if month_meta is None:
        await update.effective_message.reply_text("No open month right now.")
        return

    month = month_meta["month"]
    db.remove_registration(scope, month, target["user_id"])
    db.remove_waitlist_entry(scope, month, target["user_id"])
    await update.effective_message.reply_text(
        f"Removed {target['name']} from the squad and waitlist."
    )
    await refresh_signup_message(context.bot, scope, chat_id, month)


@require_group_admin
async def finalize(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    scope = resolve_scope(update)
    month_meta = db.get_open_month(scope)
    if month_meta is None:
        await update.effective_message.reply_text("No open month to finalize.")
        return

    max_players = MAX_PLAYERS
    if context.args:
        try:
            max_players = int(context.args[0])
            if max_players <= 0:
                raise ValueError
        except ValueError:
            await update.effective_message.reply_text(
                "max_players must be a positive whole number."
            )
            return

    month = month_meta["month"]
    registrations = db.list_registrations(scope, month)  # already join-ordered

    overflow = registrations[max_players:]
    registrations = registrations[:max_players]
    for r in overflow:
        db.remove_registration(scope, month, r["user_id"])

    if not registrations:
        await update.effective_message.reply_text(
            "No players registered — nothing to finalize."
        )
        return

    total_cost = month_meta["total_cost"]
    cost_per_player = split_cost(total_cost, len(registrations))
    for r in registrations:
        db.add_transaction(
            scope,
            r["user_id"],
            -cost_per_player,
            f"{month} court share",
            created_by="system",
        )

    db.set_month_cost_per_player(scope, month, cost_per_player)
    db.set_month_status(scope, month, "finalized")

    lines = [
        f"Finalized {month}: {len(registrations)} players, ${cost_per_player:.2f} each charged."
    ]
    if overflow:
        lines.append(
            f"{len(overflow)} couldn't be fit and were removed (squad capped at {max_players})."
        )
    await update.effective_message.reply_text("\n".join(lines))
    await refresh_signup_message(context.bot, scope, chat_id, month)


@require_group_admin
async def charge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _adjust_balance(
        update, context, sign=-1, label="Charged", default_desc="charge"
    )


@require_group_admin
async def credit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _adjust_balance(
        update, context, sign=1, label="Credited", default_desc="credit"
    )


@require_group_admin
async def paid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _adjust_balance(
        update,
        context,
        sign=1,
        label="Recorded payment of",
        default_desc="payment received",
    )


async def _adjust_balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    sign: int,
    label: str,
    default_desc: str,
) -> None:
    target, rest = resolve_target_and_rest(update, context)
    if target is None:
        await update.effective_message.reply_text(
            "Reply to their message, or specify @username, followed by an amount."
        )
        return

    if not rest:
        await update.effective_message.reply_text("Usage: <amount> [description]")
        return

    try:
        amount = float(rest[0])
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text("Amount must be a positive number.")
        return

    description = " ".join(rest[1:]).strip() or default_desc
    scope = resolve_scope(update)

    db.ensure_player_stub(scope, target["user_id"], target["name"], target["username"])
    db.add_transaction(
        scope, target["user_id"], sign * amount, description, created_by="admin"
    )

    player = db.get_player(scope, target["user_id"])
    await update.effective_message.reply_text(
        f"{label} {target['name']} ${amount:.2f} ({description}). New balance: ${player['balance']}."
    )


@require_group_admin
async def balances(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    players = db.list_players(resolve_scope(update))
    if not players:
        await update.effective_message.reply_text("No registered players yet.")
        return

    lines = [
        f"{p['name']}: ${p['balance']}"
        for p in sorted(players, key=lambda p: p["name"])
    ]
    await update.effective_message.reply_text("\n".join(lines))
