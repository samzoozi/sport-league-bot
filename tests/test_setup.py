from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram import Chat, ChatMember

from bot.handlers import setup


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
