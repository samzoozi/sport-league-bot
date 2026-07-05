from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot import db
from bot.services.attendance import attendees_for_date, game_roster
from bot.services.cards import game_card
from bot.services.mentions import mention_text_and_entities
from bot.services.months import (
    current_month,
    next_game_date,
    split_cost,
    today_for_scope,
)
from bot.services.permissions import require_group_setup
from bot.services.scope import resolve_scope, topic_thread_id


@require_group_setup
async def skip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scope = resolve_scope(update)
    user = update.effective_user

    if db.get_player(scope, user.id) is None:
        await update.effective_message.reply_text(
            "You haven't registered yet — run /register <email> <display name> first."
        )
        return

    today = today_for_scope(scope)
    month_meta = current_month(db.list_months(scope), today=today)
    if month_meta is None or month_meta["status"] != "finalized":
        await update.effective_message.reply_text(
            "No finalized squad right now — skips only apply once a month has been finalized."
        )
        return

    month = month_meta["month"]
    next_date = next_game_date(month_meta["game_dates"], today=today)
    if next_date is None:
        await update.effective_message.reply_text(
            f"No more games scheduled for {month}."
        )
        return

    if user.id not in attendees_for_date(scope, month, next_date):
        await update.effective_message.reply_text(f"You're not playing {next_date}.")
        return

    existing_skip = db.get_skip(scope, next_date, user.id)
    if (
        db.is_registered(scope, month, user.id)
        and existing_skip is not None
        and existing_skip["status"] == "open"
    ):
        await update.effective_message.reply_text(
            f"You've already requested to skip {next_date}."
        )
        return

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"Confirm skip {next_date}",
                    callback_data=f"skip:pick:{next_date}:{user.id}",
                )
            ]
        ]
    )
    await update.effective_message.reply_text(
        f"Skip the next match ({next_date})?", reply_markup=keyboard
    )


async def post_game_card(
    bot,
    scope: str,
    chat_id: int,
    thread_id: int | None,
    month: str,
    weekday: str,
    date_str: str,
) -> None:
    roster = game_roster(scope, month, date_str)
    players_by_id = {p["user_id"]: p for p in db.list_players(scope)}
    await bot.send_message(
        chat_id,
        game_card(date_str, weekday, roster, players_by_id),
        message_thread_id=thread_id,
    )


async def skip_pick_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    _, _, date_str, requester_id_str = query.data.split(":")
    chat_id = update.effective_chat.id
    scope = resolve_scope(update)
    thread_id = topic_thread_id(update)
    user = update.effective_user

    if user.id != int(requester_id_str):
        await query.answer(
            "This isn't your skip request — run /skip yourself.", show_alert=True
        )
        return

    month_meta = current_month(db.list_months(scope), today=today_for_scope(scope))
    if month_meta is None or date_str not in month_meta["game_dates"]:
        await query.answer("This game is no longer valid.", show_alert=True)
        return

    month = month_meta["month"]
    if user.id not in attendees_for_date(scope, month, date_str):
        await query.answer("You're not playing this game.", show_alert=True)
        return

    if db.is_registered(scope, month, user.id):
        existing_skip = db.get_skip(scope, date_str, user.id)
        if existing_skip is not None and existing_skip["status"] == "open":
            await query.answer("You've already skipped this game.")
            return
        owner_id = user.id
        if existing_skip is None:
            db.add_skip(scope, date_str, user.id)
        else:
            db.reopen_skip(scope, date_str, owner_id, vacated_by=user.id)
    else:
        occupied = db.get_occupied_skip(scope, date_str, user.id)
        if occupied is None:
            await query.answer("You're not playing this game.", show_alert=True)
            return
        owner_id = int(occupied["user_id"])
        db.reopen_skip(scope, date_str, owner_id, vacated_by=user.id)

    await query.edit_message_text(
        f"You're marked as skipping {date_str}. Looking for a replacement..."
    )
    await query.answer()

    offer_sent = await offer_next(
        context.bot, scope, chat_id, thread_id, date_str, owner_id
    )
    if not offer_sent:
        await post_game_card(
            context.bot,
            scope,
            chat_id,
            thread_id,
            month,
            month_meta["weekday"],
            date_str,
        )


async def offer_next(
    bot, scope: str, chat_id: int, thread_id: int | None, date_str: str, owner_id: int
) -> bool:
    """Returns True if a waitlist candidate was actually offered the spot
    (an actionable Accept/Decline card is now live), False if the spot was
    just announced as open with no one to offer it to."""
    # owner_id is always the original registrant's user_id — a spot's skip
    # record is keyed by them for its whole lifetime, no matter how many
    # times it's been vacated and re-filled. vacated_by tracks whoever most
    # recently backed out, purely for the "can't play" announcement text.
    skip = db.get_skip(scope, date_str, owner_id)
    announcer = db.get_player(scope, int(skip["vacated_by"]))

    waitlist = db.list_waitlist(scope, date_str)
    if not waitlist:
        prefix = ""
        suffix = (
            f" can't play {date_str}. No one is on the waitlist — the spot is open."
        )
        text, entities = mention_text_and_entities("❌ " + prefix, announcer, suffix)
        await bot.send_message(
            chat_id, text, entities=entities, message_thread_id=thread_id
        )
        return False

    candidate = db.get_player(scope, int(waitlist[0]["user_id"]))
    await _send_offer(
        bot, scope, chat_id, thread_id, date_str, owner_id, announcer, candidate
    )
    return True


async def _send_offer(
    bot,
    scope: str,
    chat_id: int,
    thread_id: int | None,
    date_str: str,
    owner_id: int,
    announcer: dict,
    candidate: dict,
) -> None:
    prefix = f"❌ {announcer['name']} can't play {date_str}. "
    suffix = ", you're up — want to play?"
    text, entities = mention_text_and_entities(prefix, candidate, suffix)
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Accept",
                    callback_data=f"replace:accept:{date_str}:{owner_id}:{candidate['user_id']}",
                ),
                InlineKeyboardButton(
                    "❌ Decline",
                    callback_data=f"replace:decline:{date_str}:{owner_id}:{candidate['user_id']}",
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

    month_meta = current_month(db.list_months(scope), today=today_for_scope(scope))
    if month_meta is None:
        await query.answer("This offer is no longer valid.", show_alert=True)
        return

    skip = db.get_skip(scope, date_str, skipper_id)
    if skip is None or skip["status"] != "open":
        await query.answer("This spot has already been filled.", show_alert=True)
        return

    if action == "decline":
        db.remove_waitlist_entry(scope, date_str, candidate_id)
        await query.edit_message_text(query.message.text + "\n\n(declined)")
        await query.answer()
        await offer_next(context.bot, scope, chat_id, thread_id, date_str, skipper_id)
        return

    still_on_waitlist = any(
        w["user_id"] == candidate_id for w in db.list_waitlist(scope, date_str)
    )
    if not still_on_waitlist:
        await query.answer(
            "You left the waitlist for this date — the offer is no longer valid.",
            show_alert=True,
        )
        await query.edit_message_text(
            query.message.text + "\n\n(no longer available — you left the waitlist)"
        )
        await offer_next(context.bot, scope, chat_id, thread_id, date_str, skipper_id)
        return

    if candidate_id in attendees_for_date(scope, month_meta["month"], date_str):
        await query.answer(
            "You're already playing this game via a different spot.", show_alert=True
        )
        db.remove_waitlist_entry(scope, date_str, candidate_id)
        await query.edit_message_text(
            query.message.text + "\n\n(already playing — skipped)"
        )
        await offer_next(context.bot, scope, chat_id, thread_id, date_str, skipper_id)
        return

    db.remove_waitlist_entry(scope, date_str, candidate_id)
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

    await post_game_card(
        context.bot,
        scope,
        chat_id,
        thread_id,
        month_meta["month"],
        month_meta["weekday"],
        date_str,
    )
