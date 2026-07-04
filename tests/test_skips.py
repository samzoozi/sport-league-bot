from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot import db
from bot.handlers.admin import removeplayer
from bot.handlers.skips import replace_callback, skip_pick_callback

SCOPE = "GROUP#-1009876543210"
MONTH = "2026-08"
DATE = "2026-08-10"


def _setup_squad():
    db.create_group(SCOPE, "Test Group", "Monday")
    db.create_month(SCOPE, MONTH, "Monday", [DATE], total_cost=100)
    db.set_month_status(SCOPE, MONTH, "finalized")
    for uid, name in ((1, "Layla"), (2, "Afsaneh")):
        db.upsert_player(SCOPE, uid, name, None, f"p{uid}@example.com")
        db.add_registration(SCOPE, MONTH, uid, added_by="self")


def _make_callback_update(user_id: int, data: str):
    update = SimpleNamespace(
        callback_query=SimpleNamespace(
            data=data, answer=AsyncMock(), edit_message_text=AsyncMock()
        ),
        effective_chat=SimpleNamespace(id=-1009876543210),
        effective_message=SimpleNamespace(is_topic_message=False),
        effective_user=SimpleNamespace(id=user_id),
    )
    context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))
    return update, context


async def test_skip_after_accepting_own_replacement_reopens_the_skip():
    _setup_squad()

    # Afsaneh (2) skips the game.
    update, context = _make_callback_update(2, f"skip:pick:{DATE}")
    await skip_pick_callback(update, context)
    assert db.get_skip(SCOPE, DATE, 2)["status"] == "open"

    # She then joins the waitlist and accepts her own now-open spot back.
    db.add_waitlist(SCOPE, DATE, 2)
    update, context = _make_callback_update(2, f"replace:accept:{DATE}:2:2")
    await replace_callback(update, context)
    skip = db.get_skip(SCOPE, DATE, 2)
    assert skip["status"] == "replaced"
    assert int(skip["replacement_id"]) == 2

    # Tapping "skip" again should NOT be rejected as "already skipped" — she's
    # legitimately playing again and should be able to back out for real this
    # time, reopening the spot instead of being silently blocked forever.
    update, context = _make_callback_update(2, f"skip:pick:{DATE}")
    await skip_pick_callback(update, context)

    already_skipped_alerts = [
        call
        for call in update.callback_query.answer.await_args_list
        if call.args and "already" in call.args[0].lower()
    ]
    assert already_skipped_alerts == []

    skip = db.get_skip(SCOPE, DATE, 2)
    assert skip["status"] == "open"
    assert skip["replacement_id"] is None


async def test_removeplayer_offers_the_vacated_spot_to_the_waitlist():
    _setup_squad()
    db.upsert_player(SCOPE, 3, "Waitlist Player", None, "p3@example.com")
    db.add_waitlist(SCOPE, DATE, 3)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1009876543210, type="group"),
        effective_message=SimpleNamespace(
            reply_to_message=SimpleNamespace(
                from_user=SimpleNamespace(id=2, full_name="Afsaneh", username=None)
            ),
            entities=None,
            is_topic_message=False,
            reply_text=AsyncMock(),
        ),
        effective_user=SimpleNamespace(id=1),
    )
    context = SimpleNamespace(
        args=[DATE],
        bot=SimpleNamespace(
            send_message=AsyncMock(),
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status="creator")),
        ),
    )

    await removeplayer(update, context)

    # Afsaneh's spot is marked open, and — unlike the old silent-removal
    # behavior — the waitlisted player (3) gets offered it directly, the
    # same way a real /skip would.
    assert db.get_skip(SCOPE, DATE, 2)["status"] == "open"
    offer_texts = [call.args[1] for call in context.bot.send_message.await_args_list]
    assert any("you're up" in text.lower() for text in offer_texts)
