from telegram import Update
from telegram.ext import ContextTypes

from bot import db
from bot.config import MAX_PLAYERS
from bot.services.cards import signup_card


async def refresh_signup_message(bot, chat_id: int, month: str) -> None:
    month_meta = db.get_month(chat_id, month)
    if month_meta is None or not month_meta.get("signup_message_id"):
        return

    registered = [r["user_id"] for r in db.list_registrations(chat_id, month)]
    waitlist = [w["user_id"] for w in db.list_waitlist(chat_id, month)]
    players_by_id = {p["user_id"]: p for p in db.list_players(chat_id)}

    text, keyboard = signup_card(month_meta, registered, waitlist, players_by_id)
    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=month_meta["signup_message_id"],
        text=text,
        reply_markup=keyboard,
    )


async def signup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    _, action, month = query.data.split(":")
    chat_id = update.effective_chat.id
    user = update.effective_user

    if db.get_player(chat_id, user.id) is None:
        await query.answer("Please run /register <email> first.", show_alert=True)
        return

    month_meta = db.get_month(chat_id, month)
    if month_meta is None or month_meta["status"] != "open":
        await query.answer("This month is no longer open.", show_alert=True)
        return

    in_squad = db.is_registered(chat_id, month, user.id)

    if action == "join":
        if in_squad:
            await query.answer("You're already in the squad.")
        else:
            db.remove_waitlist_entry(chat_id, month, user.id)
            squad_size = len(db.list_registrations(chat_id, month))
            if squad_size >= MAX_PLAYERS:
                db.add_waitlist(chat_id, month, user.id)
                await query.answer("Squad is full — added you to the waitlist instead.")
            else:
                db.add_registration(chat_id, month, user.id, added_by="self")
                await query.answer("You're in!")

    elif action == "waitlist":
        if in_squad:
            await query.answer(
                "You're already in the squad — use Leave if you want to give up your spot."
            )
        elif any(w["user_id"] == user.id for w in db.list_waitlist(chat_id, month)):
            await query.answer("You're already on the waitlist.")
        else:
            db.add_waitlist(chat_id, month, user.id)
            await query.answer("Added to the waitlist.")

    elif action == "leave":
        was_full = len(db.list_registrations(chat_id, month)) >= MAX_PLAYERS
        db.remove_registration(chat_id, month, user.id)
        db.remove_waitlist_entry(chat_id, month, user.id)
        await query.answer("You've been removed.")

        if in_squad and was_full:
            next_up = db.list_waitlist(chat_id, month)
            if next_up:
                promoted_id = next_up[0]["user_id"]
                db.remove_waitlist_entry(chat_id, month, promoted_id)
                db.add_registration(chat_id, month, promoted_id, added_by="self")

    await refresh_signup_message(context.bot, chat_id, month)
