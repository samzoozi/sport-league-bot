from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram import Chat, ChatMember

from bot import db
from bot.handlers import setup

TZ_SCOPE = "GROUP#-100777"


def _update(chat_id, old_status, new_status, chat_type=Chat.SUPERGROUP):
    chat = SimpleNamespace(id=chat_id, type=chat_type)
    my_chat_member = SimpleNamespace(
        old_chat_member=SimpleNamespace(status=old_status),
        new_chat_member=SimpleNamespace(status=new_status),
    )
    return SimpleNamespace(effective_chat=chat, my_chat_member=my_chat_member)


def _context():
    return SimpleNamespace(bot=AsyncMock())


async def test_guard_noop_when_allowlist_disabled(monkeypatch):
    monkeypatch.setattr(setup, "ALLOWED_CHAT_IDS", None)
    update = _update(-100999, ChatMember.LEFT, ChatMember.MEMBER)
    context = _context()

    await setup.guard_chat_membership(update, context)

    context.bot.leave_chat.assert_not_called()


async def test_guard_leaves_group_not_in_allowlist(monkeypatch):
    monkeypatch.setattr(setup, "ALLOWED_CHAT_IDS", {-100123})
    update = _update(-100999, ChatMember.LEFT, ChatMember.MEMBER)
    context = _context()

    await setup.guard_chat_membership(update, context)

    context.bot.send_message.assert_awaited_once()
    context.bot.leave_chat.assert_awaited_once_with(-100999)


async def test_guard_allows_group_in_allowlist(monkeypatch):
    monkeypatch.setattr(setup, "ALLOWED_CHAT_IDS", {-100999})
    update = _update(-100999, ChatMember.LEFT, ChatMember.MEMBER)
    context = _context()

    await setup.guard_chat_membership(update, context)

    context.bot.leave_chat.assert_not_called()


async def test_guard_ignores_non_join_transitions(monkeypatch):
    # e.g. promoted from member to administrator within an already-joined group.
    monkeypatch.setattr(setup, "ALLOWED_CHAT_IDS", {-100123})
    update = _update(-100999, ChatMember.MEMBER, ChatMember.ADMINISTRATOR)
    context = _context()

    await setup.guard_chat_membership(update, context)

    context.bot.leave_chat.assert_not_called()


async def test_guard_ignores_private_chats(monkeypatch):
    monkeypatch.setattr(setup, "ALLOWED_CHAT_IDS", {-100123})
    update = _update(555, ChatMember.LEFT, ChatMember.MEMBER, chat_type=Chat.PRIVATE)
    context = _context()

    await setup.guard_chat_membership(update, context)

    context.bot.leave_chat.assert_not_called()


def _command_update(user_id, args):
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100777, type="group"),
        effective_message=SimpleNamespace(
            is_topic_message=False, reply_text=AsyncMock()
        ),
        effective_user=SimpleNamespace(id=user_id),
    )
    context = SimpleNamespace(
        args=args,
        bot=SimpleNamespace(
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status="creator"))
        ),
    )
    return update, context


def _callback_update(user_id, data, admin_status="creator"):
    update = SimpleNamespace(
        callback_query=SimpleNamespace(
            data=data, answer=AsyncMock(), edit_message_text=AsyncMock()
        ),
        effective_chat=SimpleNamespace(id=-100777),
        effective_message=SimpleNamespace(is_topic_message=False),
        effective_user=SimpleNamespace(id=user_id),
    )
    context = SimpleNamespace(
        bot=SimpleNamespace(
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status=admin_status))
        )
    )
    return update, context


async def test_settimezone_requires_group_setup_first():
    update, context = _command_update(1, ["Eastern"])

    await setup.settimezone(update, context)

    update.effective_message.reply_text.assert_awaited_once_with(
        "This group isn't set up yet. Run /setupgroup first."
    )


async def test_settimezone_with_known_label_sets_it():
    db.create_group(TZ_SCOPE, "Test Group", "Monday")
    update, context = _command_update(1, ["Eastern"])

    await setup.settimezone(update, context)

    assert db.get_group(TZ_SCOPE)["timezone"] == "America/New_York"
    update.effective_message.reply_text.assert_awaited_once_with(
        "Timezone set to Eastern Time (Toronto, NYC) (America/New_York)."
    )


async def test_settimezone_rejects_unknown_label():
    db.create_group(TZ_SCOPE, "Test Group", "Monday")
    update, context = _command_update(1, ["Atlantic"])

    await setup.settimezone(update, context)

    assert "timezone" not in db.get_group(TZ_SCOPE)
    text = update.effective_message.reply_text.await_args.args[0]
    assert "Unknown timezone" in text


async def test_settimezone_no_args_shows_a_button_per_choice():
    db.create_group(TZ_SCOPE, "Test Group", "Monday")
    update, context = _command_update(1, [])

    await setup.settimezone(update, context)

    keyboard = update.effective_message.reply_text.await_args.kwargs[
        "reply_markup"
    ].inline_keyboard
    callback_data = [button.callback_data for row in keyboard for button in row]
    assert "settimezone:Eastern" in callback_data
    assert "settimezone:UTC" in callback_data


async def test_settimezone_callback_rejects_non_admin():
    db.create_group(TZ_SCOPE, "Test Group", "Monday")
    update, context = _callback_update(1, "settimezone:Eastern", admin_status="member")

    await setup.settimezone_callback(update, context)

    update.callback_query.answer.assert_awaited_once_with(
        "Only group admins can do that.", show_alert=True
    )
    assert "timezone" not in db.get_group(TZ_SCOPE)


async def test_settimezone_callback_sets_timezone():
    db.create_group(TZ_SCOPE, "Test Group", "Monday")
    update, context = _callback_update(1, "settimezone:Pacific")

    await setup.settimezone_callback(update, context)

    assert db.get_group(TZ_SCOPE)["timezone"] == "America/Los_Angeles"
    update.callback_query.edit_message_text.assert_awaited_once_with(
        "Timezone set to Pacific Time (LA, Vancouver) (America/Los_Angeles)."
    )
