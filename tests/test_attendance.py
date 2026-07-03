from bot import db
from bot.services.attendance import attendees_for_date

SCOPE = "GROUP#-1009876543210"
MONTH = "2026-08"
DATE = "2026-08-10"


def _setup_squad():
    for uid in (1, 2, 3):
        db.upsert_player(SCOPE, uid, f"Player {uid}", None, f"p{uid}@example.com")
        db.add_registration(SCOPE, MONTH, uid, added_by="self")


def test_attendees_with_no_skips_is_full_squad():
    _setup_squad()
    attendees = attendees_for_date(SCOPE, MONTH, DATE)
    assert set(attendees) == {1, 2, 3}


def test_attendees_excludes_open_skip_with_no_replacement():
    _setup_squad()
    db.add_skip(SCOPE, DATE, 2)
    attendees = attendees_for_date(SCOPE, MONTH, DATE)
    assert set(attendees) == {1, 3}


def test_attendees_substitutes_replacement_for_skipper():
    _setup_squad()
    db.upsert_player(SCOPE, 4, "Waitlist Player", None, "p4@example.com")
    db.add_skip(SCOPE, DATE, 2)
    db.set_skip_replaced(SCOPE, DATE, 2, 4)

    attendees = attendees_for_date(SCOPE, MONTH, DATE)
    assert set(attendees) == {1, 3, 4}
    assert 2 not in attendees


def test_attendees_unaffected_on_a_different_date():
    _setup_squad()
    db.add_skip(SCOPE, DATE, 2)
    other_date_attendees = attendees_for_date(SCOPE, MONTH, "2026-08-17")
    assert set(other_date_attendees) == {1, 2, 3}


def test_attendees_excludes_slot_after_replacement_backs_out():
    _setup_squad()
    db.upsert_player(SCOPE, 4, "Waitlist Player", None, "p4@example.com")
    db.add_skip(SCOPE, DATE, 2)
    db.set_skip_replaced(SCOPE, DATE, 2, 4)

    # Player 4 (the replacement) then backs out too — the spot goes back to
    # unfilled, not back to player 2.
    db.reopen_skip(SCOPE, DATE, 2, vacated_by=4)

    attendees = attendees_for_date(SCOPE, MONTH, DATE)
    assert set(attendees) == {1, 3}
