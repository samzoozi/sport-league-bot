from telegram import Update


def resolve_scope(update: Update) -> str:
    """The DynamoDB partition key for wherever this update came from.

    A plain group (or the implicit "General" thread of a forum) is scoped by
    chat alone. A genuine forum topic message is scoped one level deeper, so
    each topic behaves as its own fully independent league."""
    chat_id = update.effective_chat.id
    message = update.effective_message
    if message is not None and getattr(message, "is_topic_message", False):
        return f"GROUP#{chat_id}#TOPIC#{message.message_thread_id}"
    return f"GROUP#{chat_id}"


def topic_thread_id(update: Update) -> int | None:
    """message_thread_id to pass to outgoing Bot API calls so they stay in the
    same topic as `update`, or None for a plain group / the General thread."""
    message = update.effective_message
    if message is not None and getattr(message, "is_topic_message", False):
        return message.message_thread_id
    return None
