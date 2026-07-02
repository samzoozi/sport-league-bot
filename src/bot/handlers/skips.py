from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot import db
from bot.services.mentions import mention_text_and_entities
from bot.services.months import split_cost
from bot.services.permissions import require_group_setup
from bot.services.scope import resolve_scope, topic_thread_id


@require_group_setup
async def skip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scope = resolve_scope(update)
    user = update.effective_user

    if db.get_player(scope, user.id) is None:
        await update.effective_message.reply_text(
            "You haven't registered yet — run /register <email> first."
        )
        return

    month_meta = db.get_latest_month(scope)
    if month_meta is None or month_meta["status"] != "finalized":
        await update.effective_message.reply_text(
            "No finalized squad right now — skips only apply once a month has been finalized."
        )
        return

    month = month_meta["month"]
    if not db.is_registered(scope, month, user.id):
        await update.effective_message.reply_text(f"You're not in the {month} squad.")
        return

    today = date.today().isoformat()
    upcoming = [d for d in month_meta["game_dates"] if d >= today]
    available = [d for d in upcoming if db.get_skip(scope, d, user.id) is None]
    if not available:
        await update.effective_message.reply_text(
            "No upcoming games to skip (or you've already skipped them all)."
        )
        return

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(d, callback_data=f"skip:pick:{d}")] for d in available]
    )
    await update.effective_message.reply_text(
        "Which game do you want to skip?", reply_markup=keyboard
    )


async def skip_pick_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    _, _, date_str = query.data.split(":")
    chat_id = update.effective_chat.id
    scope = resolve_scope(update)
    thread_id = topic_thread_id(update)
    user = update.effective_user

    month_meta = db.get_latest_month(scope)
    if month_meta is None or date_str not in month_meta["game_dates"]:
        await query.answer("This game is no longer valid.", show_alert=True)
        return

    month = month_meta["month"]
    if not db.is_registered(scope, month, user.id):
        await query.answer("You're not in the squad.", show_alert=True)
        return

    if db.get_skip(scope, date_str, user.id) is not None:
        await query.answer("You've already skipped this game.")
        return

    db.add_skip(scope, date_str, user.id)
    await query.edit_message_text(
        f"You're marked as skipping {date_str}. Looking for a replacement..."
    )
    await query.answer()

    skipper = db.get_player(scope, user.id)
    await _offer_next(context.bot, scope, chat_id, thread_id, month, date_str, skipper)


async def _offer_next(
    bot,
    scope: str,
    chat_id: int,
    thread_id: int | None,
    month: str,
    date_str: str,
    skipper: dict,
) -> None:
    waitlist = db.list_waitlist(scope, month)
    if not waitlist:
        prefix = ""
        suffix = (
            f" can't play {date_str}. No one is on the waitlist — the spot is open."
        )
        text, entities = mention_text_and_entities("❌ " + prefix, skipper, suffix)
        await bot.send_message(
            chat_id, text, entities=entities, message_thread_id=thread_id
        )
        return

    candidate = db.get_player(scope, int(waitlist[0]["user_id"]))
    prefix = f"❌ {skipper['name']} can't play {date_str}. "
    suffix = ", you're up — want to play?"
    text, entities = mention_text_and_entities(prefix, candidate, suffix)
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Accept",
                    callback_data=f"replace:accept:{date_str}:{skipper['user_id']}:{candidate['user_id']}",
                ),
                InlineKeyboardButton(
                    "❌ Decline",
                    callback_data=f"replace:decline:{date_str}:{skipper['user_id']}:{candidate['user_id']}",
                ),
            ]
        ]
    )
    await bot.send_message(
        chat_id,
        text,
        entities=entities,
        reply_markup=keyboard,
        message_thread_id=thread_id,
    )


async def replace_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    _, action, date_str, skipper_id_str, candidate_id_str = query.data.split(":")
    skipper_id = int(skipper_id_str)
    candidate_id = int(candidate_id_str)
    chat_id = update.effective_chat.id
    scope = resolve_scope(update)
    thread_id = topic_thread_id(update)
    user = update.effective_user

    if user.id != candidate_id:
        await query.answer("This offer isn't for you.", show_alert=True)
        return

    month_meta = db.get_latest_month(scope)
    if month_meta is None:
        await query.answer("This offer is no longer valid.", show_alert=True)
        return
    month = month_meta["month"]

    skip = db.get_skip(scope, date_str, skipper_id)
    if skip is None or skip["status"] != "open":
        await query.answer("This spot has already been filled.", show_alert=True)
        return

    if action == "decline":
        db.remove_waitlist_entry(scope, month, candidate_id)
        await query.edit_message_text(query.message.text + "\n\n(declined)")
        await query.answer()
        skipper = db.get_player(scope, skipper_id)
        await _offer_next(
            context.bot, scope, chat_id, thread_id, month, date_str, skipper
        )
        return

    db.remove_waitlist_entry(scope, month, candidate_id)
    db.set_skip_replaced(scope, date_str, skipper_id, candidate_id)

    skipper = db.get_player(scope, skipper_id)
    candidate = db.get_player(scope, candidate_id)

    cost_per_player = month_meta.get("cost_per_player")
    amount_line = ""
    if cost_per_player:
        per_game = split_cost(cost_per_player, len(month_meta["game_dates"]))
        amount_line = f" Please e-transfer ${per_game} to {skipper['name']}"
        if skipper.get("email"):
            amount_line += f" ({skipper['email']})"
        amount_line += "."

    await query.edit_message_text(
        f"✅ {candidate['name']} is in for {date_str}!{amount_line}"
    )
    await query.answer()
