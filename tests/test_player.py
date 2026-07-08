from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot import db
from bot.handlers import player

SCOPE = "GROUP#-100123"


def _update(user_id, args, full_name="Jane Doe", username="janedoe"):
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100123, type="group"),
        effective_message=SimpleNamespace(reply_text=AsyncMock()),
        effective_user=SimpleNamespace(
            id=user_id, full_name=full_name, username=username
        ),
    )
    context = SimpleNamespace(args=args)
    return update, context


async def test_register_with_no_args_uses_telegram_name_and_no_email():
    db.create_group(SCOPE, "Test Group", "Monday")
    update, context = _update(1, [])

    await player.register(update, context)

    saved = db.get_player(SCOPE, 1)
    assert saved["name"] == "Jane Doe"
    assert saved.get("email") is None
    update.effective_message.reply_text.assert_awaited_once_with(
        "Welcome Jane Doe! You're registered (no email set yet — run "
        "/setemail <email> to add one). Use /help to see what I can do."
    )


async def test_register_with_email_and_display_name_succeeds():
    db.create_group(SCOPE, "Test Group", "Monday")
    update, context = _update(1, ["jane@example.com", "Jane", "Doe"])

    await player.register(update, context)

    saved = db.get_player(SCOPE, 1)
    assert saved["name"] == "Jane Doe"
    assert saved["email"] == "jane@example.com"
    update.effective_message.reply_text.assert_awaited_once_with(
        "Welcome Jane Doe! You're registered with email jane@example.com. "
        "Use /help to see what I can do."
    )


async def test_register_with_only_name_leaves_email_unset():
    db.create_group(SCOPE, "Test Group", "Monday")
    update, context = _update(1, ["Janie"])

    await player.register(update, context)

    saved = db.get_player(SCOPE, 1)
    assert saved["name"] == "Janie"
    assert saved.get("email") is None


async def test_register_with_only_email_keeps_existing_name():
    db.create_group(SCOPE, "Test Group", "Monday")
    db.upsert_player(SCOPE, 1, "Janie", "janedoe", None)
    update, context = _update(1, ["jane@example.com"])

    await player.register(update, context)

    saved = db.get_player(SCOPE, 1)
    assert saved["name"] == "Janie"
    assert saved["email"] == "jane@example.com"
    update.effective_message.reply_text.assert_awaited_once_with(
        "Updated: Janie, jane@example.com."
    )


async def test_register_rejects_invalid_email_looking_token():
    db.create_group(SCOPE, "Test Group", "Monday")
    update, context = _update(1, ["jane@example"])

    await player.register(update, context)

    update.effective_message.reply_text.assert_awaited_once_with(
        "That doesn't look like a valid email."
    )
    assert db.get_player(SCOPE, 1) is None


async def test_register_again_updates_email_and_name():
    db.create_group(SCOPE, "Test Group", "Monday")
    db.upsert_player(SCOPE, 1, "Jane", "janedoe", "old@example.com")
    update, context = _update(1, ["new@example.com", "Jane", "Doe"])

    await player.register(update, context)

    saved = db.get_player(SCOPE, 1)
    assert saved["name"] == "Jane Doe"
    assert saved["email"] == "new@example.com"
    update.effective_message.reply_text.assert_awaited_once_with(
        "Updated: Jane Doe, new@example.com."
    )
