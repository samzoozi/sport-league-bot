import re

from telegram import Update
from telegram.ext import ContextTypes

from bot import db
from bot.handlers.signup import post_signup_card
from bot.services.attendance import attendees_for_date
from bot.services.cards import game_card
from bot.services.months import current_month, next_game_date
from bot.services.permissions import require_group_setup
from bot.services.scope import resolve_scope

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

HELP_MESSAGE = (
    "Player commands:\n"
    "/register <email> [display name] — register with this group's bot "
    "(re-run to update your email or name)\n"
    "/setemail <email> — update just your e-transfer email\n"
    "/emails — list everyone's e-transfer email\n"
    "/balance — your balance and recent transactions\n"
    "/squad — re-post the current month's signup card\n"
    "/skip — skip the next game (offers your spot to the waitlist)\n"
    "/waitlist — join the waitlist for the next game\n"
    "/nextgame — who's playing in the next game\n"
    "/games — this month's game schedule\n\n"
    "Admin commands:\n"
    "/setupgroup — one-time setup, tap a weekday (or /setupgroup <weekday> to skip the buttons)\n"
    "/newmonth <YYYY-MM> <total_cost> [skip-dates...] — open signups for a month "
    "(e.g. /newmonth 2026-08 240 2026-08-03)\n"
    "/deletemonth <YYYY-MM> — delete an open (non-finalized) month\n"
    "/addplayer, /removeplayer — reply to their message or use @username\n"
    "/finalize [max_players] — lock the squad and charge everyone their share\n"
    "/charge @user <amount> <desc> — reply to their message or use @username\n"
    "/credit @user <amount> <desc> — reply to their message or use @username\n"
    "/chargeall <YYYY-MM> <amount> <desc> — charge that month's whole squad the same amount each\n"
    "/creditall <YYYY-MM> <amount> <desc> — credit that month's whole squad the same amount each\n"
    "/paid @user <amount> — record a payment received\n"
    "/balances — show everyone's balance"
)


def _display_name(update: Update) -> str:
    user = update.effective_user
    return user.full_name or user.username or str(user.id)


async def help_(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP_MESSAGE)


@require_group_setup
async def register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text(
            "Usage: /register <email> [display name]"
        )
        return

    email = context.args[0]
    if not EMAIL_RE.match(email):
        await update.effective_message.reply_text(
            "That doesn't look like a valid email."
        )
        return

    display_name = " ".join(context.args[1:]).strip()
    scope = resolve_scope(update)
    user = update.effective_user
    name = display_name or _display_name(update)

    already_registered = db.get_player(scope, user.id) is not None
    db.upsert_player(scope, user.id, name, user.username, email)

    if already_registered:
        await update.effective_message.reply_text(f"Updated: {name}, {email}.")
    else:
        await update.effective_message.reply_text(
            f"Welcome {name}! You're registered with email {email}. Use /help to see what I can do."
        )


@require_group_setup
async def setemail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scope = resolve_scope(update)
    user = update.effective_user
    player = db.get_player(scope, user.id)
    if player is None:
        await update.effective_message.reply_text(
            "You haven't registered yet — run /register <email> [display name] first."
        )
        return

    if not context.args:
        await update.effective_message.reply_text("Usage: /setemail <email>")
        return

    email = context.args[0]
    if not EMAIL_RE.match(email):
        await update.effective_message.reply_text(
            "That doesn't look like a valid email."
        )
        return

    db.upsert_player(scope, user.id, player["name"], user.username, email)
    await update.effective_message.reply_text(f"Email updated to {email}.")


@require_group_setup
async def emails(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    players = db.list_players(resolve_scope(update))
    with_email = [p for p in players if p.get("email")]
    if not with_email:
        await update.effective_message.reply_text(
            "No one has set an e-transfer email yet."
        )
        return

    lines = [
        f"{p['name']}: {p['email']}"
        for p in sorted(with_email, key=lambda p: p["name"])
    ]
    await update.effective_message.reply_text("\n".join(lines))


@require_group_setup
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scope = resolve_scope(update)
    user = update.effective_user
    player = db.get_player(scope, user.id)
    if player is None:
        await update.effective_message.reply_text(
            "You haven't registered yet — run /register <email> [display name]."
        )
        return

    lines = [f"Balance: ${player['balance']}"]
    txns = db.list_transactions(scope, user.id, limit=5)
    if txns:
        lines.append("\nRecent transactions:")
        for t in txns:
            lines.append(f"  ${t['amount']} — {t['description']}")
    await update.effective_message.reply_text("\n".join(lines))


@require_group_setup
async def squad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scope = resolve_scope(update)
    month_meta = db.get_open_month(scope)
    if month_meta is None:
        await update.effective_message.reply_text("No open month right now.")
        return

    await post_signup_card(
        update.effective_message.reply_text, scope, month_meta["month"]
    )


@require_group_setup
async def waitlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scope = resolve_scope(update)
    user = update.effective_user

    if db.get_player(scope, user.id) is None:
        await update.effective_message.reply_text(
            "You haven't registered yet — run /register <email> [display name] first."
        )
        return

    month_meta = current_month(db.list_months(scope))
    if month_meta is None or month_meta["status"] != "finalized":
        await update.effective_message.reply_text(
            "Waitlist requests only apply once a month has been finalized."
        )
        return

    next_date = next_game_date(month_meta["game_dates"])
    if next_date is None:
        await update.effective_message.reply_text(
            f"No more games scheduled for {month_meta['month']}."
        )
        return

    month = month_meta["month"]
    if db.is_registered(scope, month, user.id):
        await update.effective_message.reply_text("You're already in the squad.")
        return

    if any(w["user_id"] == user.id for w in db.list_waitlist(scope, next_date)):
        await update.effective_message.reply_text(
            f"You're already on the waitlist for {next_date}."
        )
        return

    db.add_waitlist(scope, next_date, user.id)
    await update.effective_message.reply_text(f"Added to the waitlist for {next_date}.")


@require_group_setup
async def nextgame(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scope = resolve_scope(update)
    month_meta = current_month(db.list_months(scope))
    if month_meta is None or month_meta["status"] != "finalized":
        await update.effective_message.reply_text("No finalized squad right now.")
        return

    next_date = next_game_date(month_meta["game_dates"])
    if next_date is None:
        await update.effective_message.reply_text(
            f"No more games scheduled for {month_meta['month']}."
        )
        return

    attendee_ids = attendees_for_date(scope, month_meta["month"], next_date)
    players_by_id = {p["user_id"]: p for p in db.list_players(scope)}
    names = [
        players_by_id.get(uid, {}).get("name", f"user {uid}") for uid in attendee_ids
    ]

    await update.effective_message.reply_text(
        game_card(next_date, month_meta["weekday"], names)
    )


@require_group_setup
async def games(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scope = resolve_scope(update)
    month_meta = current_month(db.list_months(scope))
    if month_meta is None:
        await update.effective_message.reply_text("No active month right now.")
        return

    month = month_meta["month"]
    lines = [f"{month} schedule ({month_meta['weekday']}s):"]
    for d in month_meta["game_dates"]:
        if month_meta["status"] == "finalized":
            count = len(attendees_for_date(scope, month, d))
            lines.append(f"{d}: {count} confirmed")
        else:
            lines.append(f"{d}: signups open")

    await update.effective_message.reply_text("\n".join(lines))
