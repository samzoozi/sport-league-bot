from types import SimpleNamespace

from bot.services.scope import resolve_scope, topic_thread_id


def _update(chat_id, is_topic_message=False, message_thread_id=None):
    message = SimpleNamespace(
        is_topic_message=is_topic_message, message_thread_id=message_thread_id
    )
    chat = SimpleNamespace(id=chat_id)
    return SimpleNamespace(effective_chat=chat, effective_message=message)


def test_resolve_scope_plain_group():
    update = _update(chat_id=-100123)
    assert resolve_scope(update) == "GROUP#-100123"


def test_resolve_scope_forum_topic_message():
    update = _update(chat_id=-100123, is_topic_message=True, message_thread_id=42)
    assert resolve_scope(update) == "GROUP#-100123#TOPIC#42"


def test_resolve_scope_forum_general_thread_is_not_scoped_as_topic():
    # Telegram's implicit "General" thread messages have is_topic_message=False,
    # so they should behave the same as a plain (non-forum) group.
    update = _update(chat_id=-100123, is_topic_message=False, message_thread_id=1)
    assert resolve_scope(update) == "GROUP#-100123"


def test_topic_thread_id_returns_none_for_plain_group():
    update = _update(chat_id=-100123)
    assert topic_thread_id(update) is None


def test_topic_thread_id_returns_thread_for_forum_topic():
    update = _update(chat_id=-100123, is_topic_message=True, message_thread_id=42)
    assert topic_thread_id(update) == 42
