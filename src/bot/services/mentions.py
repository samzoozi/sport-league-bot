from telegram import MessageEntity, User


def mention_text_and_entities(
    prefix: str, player: dict, suffix: str
) -> tuple[str, list[MessageEntity]]:
    """Build a message with a real tap-to-open mention of `player` embedded between
    `prefix` and `suffix`. Uses @username plain text when available (Telegram
    auto-links it, no entity needed); falls back to a text_mention entity
    (works even without a public username) otherwise."""
    username = player.get("username")
    name = player["name"]

    if username:
        return f"{prefix}@{username}{suffix}", []

    text = f"{prefix}{name}{suffix}"
    entity = MessageEntity(
        type=MessageEntity.TEXT_MENTION,
        offset=len(prefix),
        length=len(name),
        user=User(id=int(player["user_id"]), first_name=name, is_bot=False),
    )
    return text, [entity]
