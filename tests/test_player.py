from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot import db
from bot.handlers import player

SCOPE = "GROUP#-100123"


def _update(user_id, args):
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100123, type="group"),
        effective_message=SimpleNamespace(reply_text=AsyncMock()),
        effective_user=SimpleNamespace(
            id=user_id, full_name="Jane Doe", username="janedoe"
        ),
    )
    context = SimpleNamespace(args=args)
    return update, context


async def test_register_requires_a_display_name():
    db.create_group(SCOPE, "Test Group", "Monday")
    update, context = _update(1, ["jane@example.com"])

    await player.register(update, context)

    update.effective_message.reply_text.assert_awaited_once_with(
        "Usage: /register <email> <display name>"
    )
    assert db.get_player(SCOPE, 1) is None


async def test_register_with_email_and_display_name_succeeds():
    db.create_group(SCOPE, "Test Group", "Monday")
    update, context = _update(1, ["jane@example.com", "Jane", "Doe"])

    await player.register(update, context)

    saved = db.get_player(SCOPE, 1)
    assert saved["name"] == "Jane Doe"
    assert saved["email"] == "jane@example.com"
