import math

from telegram import Update
from telegram.ext import ContextTypes

from bot import db
from bot.config import MAX_PLAYERS
from bot.handlers.signup import post_signup_card, refresh_signup_message
from bot.handlers.skips import offer_next, post_game_card
from bot.services.attendance import attendees_for_date
from bot.services.months import (
    game_dates_for_month,
    month_for_date,
    parse_month,
    split_cost,
)
from bot.services.permissions import require_group_admin, require_group_setup
from bot.services.scope import resolve_scope, topic_thread_id
from bot.services.users import (
    resolve_target_and_rest,
    resolve_target_user,
    resolve_targets_and_rest,
)

NO_BALANCE_CHANGE_WARNING = (
    "This does NOT adjust anyone's balance — use /charge or /credit manually "
    "if money needs to change hands."
)


def _parse_positive_amount(text: str) -> float | None:
    """Parse a user-supplied amount, rejecting anything that isn't a positive,
    finite number — plain float() also accepts "inf"/"nan", which would
    otherwise slip past a bare `<= 0` check."""
    try:
        amount = float(text)
    except ValueError:
        return None
    if not math.isfinite(amount) or amount <= 0:
        return None
    return amount


@require_group_admin
@require_group_setup
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

    total_cost = _parse_positive_amount(args[1])
    if total_cost is None:
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
    await post_signup_card(update.effective_message.reply_text, scope, month_key)


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
async def addtosquad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    scope = resolve_scope(update)
    target = resolve_target_user(update, context)
    if target is None:
        await update.effective_message.reply_text(
            "Reply to their message with /addtosquad, or run /addtosquad @username "
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

    db.add_registration(scope, month, target["user_id"], added_by="admin")
    await update.effective_message.reply_text(f"Added {target['name']} to the squad.")
    await refresh_signup_message(context.bot, scope, chat_id, month)


@require_group_admin
async def removefromsquad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    scope = resolve_scope(update)
    target = resolve_target_user(update, context)
    if target is None:
        await update.effective_message.reply_text(
            "Reply to their message with /removefromsquad, or run /removefromsquad @username."
        )
        return

    month_meta = db.get_open_month(scope)
    if month_meta is None:
        await update.effective_message.reply_text("No open month right now.")
        return

    month = month_meta["month"]
    db.remove_registration(scope, month, target["user_id"])
    await update.effective_message.reply_text(
        f"Removed {target['name']} from the squad."
    )
    await refresh_signup_message(context.bot, scope, chat_id, month)


@require_group_admin
async def addplayer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scope = resolve_scope(update)
    chat_id = update.effective_chat.id
    thread_id = topic_thread_id(update)
    target, rest = resolve_target_and_rest(update, context)
    if target is None or not rest:
        await update.effective_message.reply_text(
            "Usage: reply to their message, or use @username, followed by the game "
            "date — e.g. /addplayer @username 2026-08-10"
        )
        return

    game_date = rest[0]
    month_meta = month_for_date(db.list_months(scope), game_date)
    if month_meta is None:
        await update.effective_message.reply_text(
            f"{game_date} isn't a scheduled game date for any month."
        )
        return
    if month_meta["status"] != "finalized":
        await update.effective_message.reply_text(
            f"{month_meta['month']} hasn't been finalized yet."
        )
        return

    month = month_meta["month"]
    db.ensure_player_stub(scope, target["user_id"], target["name"], target["username"])

    if target["user_id"] in attendees_for_date(scope, month, game_date):
        await update.effective_message.reply_text(
            f"{target['name']} is already playing {game_date}."
        )
        return

    db.add_extra_attendee(scope, game_date, target["user_id"])
    await update.effective_message.reply_text(
        f"Added {target['name']} to {game_date}. {NO_BALANCE_CHANGE_WARNING}"
    )
    await post_game_card(
        context.bot, scope, chat_id, thread_id, month, month_meta["weekday"], game_date
    )


@require_group_admin
async def removeplayer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scope = resolve_scope(update)
    chat_id = update.effective_chat.id
    thread_id = topic_thread_id(update)
    target, rest = resolve_target_and_rest(update, context)
    if target is None or not rest:
        await update.effective_message.reply_text(
            "Usage: reply to their message, or use @username, followed by the game "
            "date — e.g. /removeplayer @username 2026-08-10"
        )
        return

    game_date = rest[0]
    month_meta = month_for_date(db.list_months(scope), game_date)
    if month_meta is None:
        await update.effective_message.reply_text(
            f"{game_date} isn't a scheduled game date for any month."
        )
        return
    if month_meta["status"] != "finalized":
        await update.effective_message.reply_text(
            f"{month_meta['month']} hasn't been finalized yet."
        )
        return

    month = month_meta["month"]
    user_id = target["user_id"]

    if user_id not in attendees_for_date(scope, month, game_date):
        await update.effective_message.reply_text(
            f"{target['name']} isn't playing {game_date}."
        )
        return

    owner_id = None
    if db.get_extra_attendee(scope, game_date, user_id) is not None:
        db.remove_extra_attendee(scope, game_date, user_id)
    elif (
        db.is_registered(scope, month, user_id)
        and db.get_skip(scope, game_date, user_id) is None
    ):
        db.add_skip(scope, game_date, user_id)
        owner_id = user_id
    else:
        occupied = db.get_occupied_skip(scope, game_date, user_id)
        if occupied is not None:
            owner_id = int(occupied["user_id"])
            db.reopen_skip(scope, game_date, owner_id, vacated_by=user_id)

    await update.effective_message.reply_text(
        f"Removed {target['name']} from {game_date}. {NO_BALANCE_CHANGE_WARNING}"
    )
    if owner_id is not None:
        await offer_next(context.bot, scope, chat_id, thread_id, game_date, owner_id)
    await post_game_card(
        context.bot, scope, chat_id, thread_id, month, month_meta["weekday"], game_date
    )


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
    await post_signup_card(update.effective_message.reply_text, scope, month)


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
    targets, unresolved, rest = resolve_targets_and_rest(update, context)

    if unresolved:
        await update.effective_message.reply_text(
            f"Couldn't find {', '.join(unresolved)} — they need to have messaged "
            "in this group before you can @mention them by username."
        )
        return

    if not targets:
        await update.effective_message.reply_text(
            "Reply to their message, or specify @username(s), followed by an amount."
        )
        return

    if not rest:
        await update.effective_message.reply_text("Usage: <amount> [description]")
        return

    amount = _parse_positive_amount(rest[0])
    if amount is None:
        await update.effective_message.reply_text("Amount must be a positive number.")
        return

    description = " ".join(rest[1:]).strip() or default_desc
    scope = resolve_scope(update)

    balances = []
    for target in targets:
        db.ensure_player_stub(
            scope, target["user_id"], target["name"], target["username"]
        )
        db.add_transaction(
            scope, target["user_id"], sign * amount, description, created_by="admin"
        )
        player = db.get_player(scope, target["user_id"])
        balances.append((target["name"], player["balance"]))

    if len(balances) == 1:
        name, balance = balances[0]
        await update.effective_message.reply_text(
            f"{label} {name} ${amount:.2f} ({description}). New balance: ${balance}."
        )
    else:
        names = ", ".join(name for name, _ in balances)
        balances_text = ", ".join(f"{name} ${balance}" for name, balance in balances)
        await update.effective_message.reply_text(
            f"{label} ${amount:.2f} ({description}) for {names}. "
            f"New balances: {balances_text}."
        )


@require_group_admin
async def chargeall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _adjust_balance_all(update, context, sign=-1, label="Charged", verb="charge")


@require_group_admin
async def creditall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _adjust_balance_all(update, context, sign=1, label="Credited", verb="credit")


async def _adjust_balance_all(
    update: Update, context: ContextTypes.DEFAULT_TYPE, sign: int, label: str, verb: str
) -> None:
    args = context.args
    if len(args) < 2:
        await update.effective_message.reply_text(
            f"Usage: /{verb}all <YYYY-MM> <amount> [description]"
        )
        return

    month_key = args[0]
    amount = _parse_positive_amount(args[1])
    if amount is None:
        await update.effective_message.reply_text("Amount must be a positive number.")
        return

    description = " ".join(args[2:]).strip() or verb
    scope = resolve_scope(update)
    registrations = db.list_registrations(scope, month_key)
    if not registrations:
        await update.effective_message.reply_text(f"No squad found for {month_key}.")
        return

    players_by_id = {p["user_id"]: p for p in db.list_players(scope)}
    for r in registrations:
        db.add_transaction(
            scope, r["user_id"], sign * amount, description, created_by="admin"
        )

    names = [
        players_by_id.get(r["user_id"], {}).get("name", f"user {r['user_id']}")
        for r in registrations
    ]
    await update.effective_message.reply_text(
        f"{label} {len(registrations)} players ${amount:.2f} each ({description}): {', '.join(names)}."
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
