from types import SimpleNamespace

from bot import db
from bot.services.users import resolve_targets_and_rest

SCOPE = "GROUP#-100888"


def _update(reply_to=None, entities=None, text=None, args=None):
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100888, type="group"),
        effective_message=SimpleNamespace(
            reply_to_message=reply_to,
            entities=entities,
            text=text,
        ),
    )
    context = SimpleNamespace(args=args or [])
    return update, context


def _mention_entity(offset, length, user_id, name, username=None):
    return SimpleNamespace(
        type="text_mention",
        offset=offset,
        length=length,
        user=SimpleNamespace(id=user_id, full_name=name, username=username),
    )


def test_resolve_targets_reply_to_message_is_a_single_target():
    reply_to = SimpleNamespace(
        from_user=SimpleNamespace(id=5, full_name="Carol", username=None)
    )
    update, context = _update(reply_to=reply_to, args=["20"])

    targets, unresolved, rest = resolve_targets_and_rest(update, context)

    assert [t["user_id"] for t in targets] == [5]
    assert unresolved == []
    assert rest == ["20"]


def test_resolve_targets_multiple_mention_picker_taps():
    entities = [
        _mention_entity(0, 5, 2, "Alice"),
        _mention_entity(6, 3, 3, "Bob"),
    ]
    update, context = _update(entities=entities, text="Alice Bob 20 team fee")

    targets, unresolved, rest = resolve_targets_and_rest(update, context)

    assert [t["user_id"] for t in targets] == [2, 3]
    assert unresolved == []
    assert rest == ["20", "team", "fee"]


def test_resolve_targets_multiple_usernames():
    db.create_group(SCOPE, "Test Group", "Monday")
    db.upsert_player(SCOPE, 2, "Alice", "alice", "alice@example.com")
    db.upsert_player(SCOPE, 3, "Bob", "bob", "bob@example.com")
    update, context = _update(args=["@alice", "@bob", "20", "court", "fee"])

    targets, unresolved, rest = resolve_targets_and_rest(update, context)

    assert [t["user_id"] for t in targets] == [2, 3]
    assert unresolved == []
    assert rest == ["20", "court", "fee"]


def test_resolve_targets_reports_unresolved_username_without_consuming_the_amount():
    db.create_group(SCOPE, "Test Group", "Monday")
    db.upsert_player(SCOPE, 2, "Alice", "alice", "alice@example.com")
    update, context = _update(args=["@alice", "@ghost", "20"])

    targets, unresolved, rest = resolve_targets_and_rest(update, context)

    assert [t["user_id"] for t in targets] == [2]
    assert unresolved == ["@ghost"]
    assert rest == ["20"]


def test_resolve_targets_no_target_returns_empty_list():
    db.create_group(SCOPE, "Test Group", "Monday")
    update, context = _update(args=["20", "court", "fee"])

    targets, unresolved, rest = resolve_targets_and_rest(update, context)

    assert targets == []
    assert unresolved == []
    assert rest == ["20", "court", "fee"]
