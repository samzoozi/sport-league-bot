from telegram import Update

from bot import db
from bot.services.scope import resolve_scope


def resolve_target_user(update: Update, context) -> dict | None:
    message = update.effective_message

    if message.reply_to_message is not None:
        user = message.reply_to_message.from_user
        return {"user_id": user.id, "name": user.full_name, "username": user.username}

    for entity in message.entities or []:
        if entity.type == "text_mention":
            user = entity.user
            return {
                "user_id": user.id,
                "name": user.full_name,
                "username": user.username,
            }

    if context.args:
        username = context.args[0].lstrip("@").lower()
        for player in db.list_players(resolve_scope(update)):
            if (player.get("username") or "").lower() == username:
                return {
                    "user_id": player["user_id"],
                    "name": player["name"],
                    "username": player.get("username"),
                }

    return None


def _lookup_by_username(scope: str, username: str) -> dict | None:
    username = username.lstrip("@").lower()
    for player in db.list_players(scope):
        if (player.get("username") or "").lower() == username:
            return {
                "user_id": player["user_id"],
                "name": player["name"],
                "username": player.get("username"),
            }
    return None


def resolve_target_and_rest(update: Update, context) -> tuple[dict | None, list[str]]:
    """Like resolve_target_user, but for commands that take extra positional args
    after the target (e.g. `/charge @user 20 court fee`). Only consumes args[0] as
    a username when it's an explicit @mention, so the remaining args (amount,
    description, ...) are never mistaken for a username."""
    message = update.effective_message
    args = list(context.args)

    if message.reply_to_message is not None:
        user = message.reply_to_message.from_user
        return {
            "user_id": user.id,
            "name": user.full_name,
            "username": user.username,
        }, args

    for entity in message.entities or []:
        if entity.type == "text_mention":
            user = entity.user
            # The mention's display name (e.g. "Layla Zon") is literal text in the
            # message, so it also shows up as tokens in `args`. Use the entity's
            # exact offset/length to drop just that span, however many words it is,
            # rather than guessing how many tokens to strip.
            remainder = message.text[entity.offset + entity.length :].strip()
            rest = remainder.split() if remainder else []
            return {
                "user_id": user.id,
                "name": user.full_name,
                "username": user.username,
            }, rest

    if args and args[0].startswith("@"):
        target = _lookup_by_username(resolve_scope(update), args[0])
        return target, args[1:]

    return None, args
