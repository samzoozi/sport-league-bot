from telegram import Update
from telegram.ext import ContextTypes

from bot import db
from bot.services.months import WEEKDAY_NAMES, parse_weekday
from bot.services.permissions import require_group_admin
from bot.services.scope import resolve_scope


@require_group_admin
async def setupgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text(
            f"Usage: /setupgroup <weekday>, e.g. /setupgroup {WEEKDAY_NAMES[0]}"
        )
        return

    weekday_index = parse_weekday(context.args[0])
    if weekday_index is None:
        await update.effective_message.reply_text(
            f"Unknown weekday '{context.args[0]}'. Use one of: {', '.join(WEEKDAY_NAMES)}"
        )
        return

    chat = update.effective_chat
    scope = resolve_scope(update)
    if db.get_group(scope) is not None:
        await update.effective_message.reply_text(
            f"This group is already set up for {WEEKDAY_NAMES[weekday_index]} games."
        )
        return

    db.create_group(
        scope,
        chat.title or chat.full_name or str(chat.id),
        WEEKDAY_NAMES[weekday_index],
    )
    await update.effective_message.reply_text(
        f"All set! Games are on {WEEKDAY_NAMES[weekday_index]}s. "
        f"An admin can now run /newmonth to open signups."
    )
