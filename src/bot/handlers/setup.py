from telegram import Chat, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot import db
from bot.services.months import WEEKDAY_NAMES, parse_weekday
from bot.services.permissions import is_group_admin, require_group_admin
from bot.services.scope import resolve_scope


def _group_title(chat: Chat) -> str:
    return chat.title or chat.full_name or str(chat.id)


def _finish_setup(chat: Chat, scope: str, weekday: str) -> str:
    db.create_group(scope, _group_title(chat), weekday)
    return f"All set! Games are on {weekday}s. An admin can now run /newmonth to open signups."


@require_group_admin
async def setupgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scope = resolve_scope(update)
    existing = db.get_group(scope)
    if existing is not None:
        await update.effective_message.reply_text(
            f"This group is already set up for {existing['weekday']} games."
        )
        return

    if context.args:
        weekday_index = parse_weekday(context.args[0])
        if weekday_index is None:
            await update.effective_message.reply_text(
                f"Unknown weekday '{context.args[0]}'. Use one of: {', '.join(WEEKDAY_NAMES)}"
            )
            return
        text = _finish_setup(update.effective_chat, scope, WEEKDAY_NAMES[weekday_index])
        await update.effective_message.reply_text(text)
        return

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(day, callback_data=f"setupgroup:{day}")]
            for day in WEEKDAY_NAMES
        ]
    )
    await update.effective_message.reply_text(
        "Which weekday do you play on?", reply_markup=keyboard
    )


async def setupgroup_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    _, weekday = query.data.split(":", 1)

    if not await is_group_admin(update, context):
        await query.answer("Only group admins can do that.", show_alert=True)
        return

    scope = resolve_scope(update)
    existing = db.get_group(scope)
    if existing is not None:
        await query.answer(
            f"Already set up for {existing['weekday']} games.", show_alert=True
        )
        return

    text = _finish_setup(update.effective_chat, scope, weekday)
    await query.edit_message_text(text)
    await query.answer()
