import functools

from telegram import Chat, Update
from telegram.ext import ContextTypes

from bot import db
from bot.services.scope import resolve_scope

ADMIN_STATUSES = {"administrator", "creator"}


async def is_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    member = await context.bot.get_chat_member(chat.id, user.id)
    return member.status in ADMIN_STATUSES


def require_group_chat(handler):
    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type == Chat.PRIVATE:
            await update.effective_message.reply_text(
                "This bot only works inside a group chat, not in DMs."
            )
            return
        return await handler(update, context)

    return wrapper


def require_group_admin(handler):
    @require_group_chat
    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await is_group_admin(update, context):
            await update.effective_message.reply_text("Only group admins can do that.")
            return
        return await handler(update, context)

    return wrapper


def require_group_setup(handler):
    @require_group_chat
    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if db.get_group(resolve_scope(update)) is None:
            await update.effective_message.reply_text(
                "This group isn't set up yet. Ask a group admin to run "
                "/setupgroup <weekday> first (e.g. /setupgroup Monday)."
            )
            return
        return await handler(update, context)

    return wrapper
