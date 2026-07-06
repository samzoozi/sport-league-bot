from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import db
from bot.handlers.admin import _parse_positive_amount, paid

SCOPE = "GROUP#-100555"


@pytest.mark.parametrize(
    "text", ["nan", "NaN", "inf", "Infinity", "-inf", "0", "-5", "abc", ""]
)
def test_parse_positive_amount_rejects_non_finite_and_non_positive(text):
    assert _parse_positive_amount(text) is None


@pytest.mark.parametrize(
    "text,expected", [("20", 20.0), ("19.99", 19.99), ("0.01", 0.01)]
)
def test_parse_positive_amount_accepts_positive_finite_numbers(text, expected):
    assert _parse_positive_amount(text) == expected


def _update(args):
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100555, type="group"),
        effective_message=SimpleNamespace(
            reply_to_message=None,
            entities=None,
            text=None,
            is_topic_message=False,
            reply_text=AsyncMock(),
        ),
        effective_user=SimpleNamespace(id=1),
    )
    context = SimpleNamespace(
        args=args,
        bot=SimpleNamespace(
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status="creator"))
        ),
    )
    return update, context


async def test_paid_single_target_via_username():
    db.create_group(SCOPE, "Test Group", "Monday")
    db.upsert_player(SCOPE, 2, "Alice", "alice", "alice@example.com")
    update, context = _update(["@alice", "20"])

    await paid(update, context)

    balance = db.get_player(SCOPE, 2)["balance"]
    update.effective_message.reply_text.assert_awaited_once_with(
        f"Recorded payment of Alice $20.00 (payment received). New balance: ${balance}."
    )


async def test_paid_multiple_usernames_charges_each_the_same_amount():
    db.create_group(SCOPE, "Test Group", "Monday")
    db.upsert_player(SCOPE, 2, "Alice", "alice", "alice@example.com")
    db.upsert_player(SCOPE, 3, "Bob", "bob", "bob@example.com")
    update, context = _update(["@alice", "@bob", "20", "court", "fee"])

    await paid(update, context)

    alice_balance = db.get_player(SCOPE, 2)["balance"]
    bob_balance = db.get_player(SCOPE, 3)["balance"]
    assert alice_balance == bob_balance
    update.effective_message.reply_text.assert_awaited_once_with(
        f"Recorded payment of $20.00 (court fee) for Alice, Bob. "
        f"New balances: Alice ${alice_balance}, Bob ${bob_balance}."
    )


async def test_paid_reports_unresolved_username_and_charges_no_one():
    db.create_group(SCOPE, "Test Group", "Monday")
    db.upsert_player(SCOPE, 2, "Alice", "alice", "alice@example.com")
    update, context = _update(["@alice", "@ghost", "20"])

    await paid(update, context)

    update.effective_message.reply_text.assert_awaited_once_with(
        "Couldn't find @ghost — they need to have messaged in this group before "
        "you can @mention them by username."
    )
    assert db.get_player(SCOPE, 2)["balance"] == 0
