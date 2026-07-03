from telegram import Update
from telegram.ext import ContextTypes

from bot import db
from bot.services.cards import signup_card
from bot.services.scope import resolve_scope


async def refresh_signup_message(bot, scope: str, chat_id: int, month: str) -> None:
    month_meta = db.get_month(scope, month)
    if month_meta is None or not month_meta.get("signup_message_id"):
        return

    registered = [r["user_id"] for r in db.list_registrations(scope, month)]
    players_by_id = {p["user_id"]: p for p in db.list_players(scope)}

    text, keyboard = signup_card(month_meta, registered, players_by_id)
    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=month_meta["signup_message_id"],
        text=text,
        reply_markup=keyboard,
    )


async def post_signup_card(reply_text, scope: str, month: str) -> None:
    """Post the squad card (open or finalized) as a fresh, visible message —
    e.g. so it clearly shows up right after /newmonth or /finalize, rather
    than only existing as a silent edit to a message that may have scrolled
    out of view. Records the new message as the canonical one to keep
    updating going forward."""
    month_meta = db.get_month(scope, month)
    registered = [r["user_id"] for r in db.list_registrations(scope, month)]
    players_by_id = {p["user_id"]: p for p in db.list_players(scope)}

    text, keyboard = signup_card(month_meta, registered, players_by_id)
    message = await reply_text(text, reply_markup=keyboard)
    db.set_month_signup_message(scope, month, message.message_id)


async def signup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    _, action, month = query.data.split(":")
    chat_id = update.effective_chat.id
    scope = resolve_scope(update)
    user = update.effective_user

    if db.get_player(scope, user.id) is None:
        await query.answer("Please run /register <email> first.", show_alert=True)
        return

    month_meta = db.get_month(scope, month)
    if month_meta is None or month_meta["status"] != "open":
        await query.answer("This month is no longer open.", show_alert=True)
        return

    in_squad = db.is_registered(scope, month, user.id)

    if action == "join":
        if in_squad:
            await query.answer("You're already in the squad.")
        else:
            db.add_registration(scope, month, user.id, added_by="self")
            await query.answer("You're in!")

    elif action == "leave":
        db.remove_registration(scope, month, user.id)
        await query.answer("You've been removed.")

    await refresh_signup_message(context.bot, scope, chat_id, month)
