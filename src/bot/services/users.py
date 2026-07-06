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


def resolve_targets_and_rest(
    update: Update, context
) -> tuple[list[dict], list[str], list[str]]:
    """Like resolve_target_and_rest, but resolves every leading target instead
    of just one, for commands where the same amount applies to several people
    at once (e.g. `/paid @alice @bob 20 court fee`, or several mention-picker
    taps in a row). A reply-to-message is still exactly one target — you can
    only reply to one message.

    Returns (targets, unresolved_usernames, rest). unresolved_usernames lists
    any leading @token that didn't match a known player, so the caller can
    name exactly which one failed instead of it silently falling through and
    getting misparsed as the amount."""
    message = update.effective_message
    args = list(context.args)

    if message.reply_to_message is not None:
        user = message.reply_to_message.from_user
        target = {
            "user_id": user.id,
            "name": user.full_name,
            "username": user.username,
        }
        return [target], [], args

    mention_entities = sorted(
        (e for e in (message.entities or []) if e.type == "text_mention"),
        key=lambda e: e.offset,
    )
    if mention_entities:
        targets = [
            {
                "user_id": e.user.id,
                "name": e.user.full_name,
                "username": e.user.username,
            }
            for e in mention_entities
        ]
        last = mention_entities[-1]
        remainder = message.text[last.offset + last.length :].strip()
        rest = remainder.split() if remainder else []
        return targets, [], rest

    scope = resolve_scope(update)
    targets = []
    unresolved = []
    i = 0
    while i < len(args) and args[i].startswith("@"):
        target = _lookup_by_username(scope, args[i])
        if target is None:
            unresolved.append(args[i])
        else:
            targets.append(target)
        i += 1

    return targets, unresolved, args[i:]
