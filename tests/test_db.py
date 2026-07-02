from decimal import Decimal

from bot import db

SCOPE = "GROUP#-1001234567890"


def test_create_and_get_group():
    assert db.get_group(SCOPE) is None
    db.create_group(SCOPE, "Test Group", "Monday")
    group = db.get_group(SCOPE)
    assert group["weekday"] == "Monday"
    assert group["title"] == "Test Group"


def test_upsert_player_creates_then_updates():
    db.upsert_player(SCOPE, 111, "Ali", "aliusername", "ali@example.com")
    player = db.get_player(SCOPE, 111)
    assert player["name"] == "Ali"
    assert player["email"] == "ali@example.com"
    assert player["balance"] == Decimal("0")

    db.upsert_player(SCOPE, 111, "Ali Z", "aliusername", "aliz@example.com")
    player = db.get_player(SCOPE, 111)
    assert player["name"] == "Ali Z"
    assert player["email"] == "aliz@example.com"


def test_ensure_player_stub_does_not_overwrite_existing():
    db.upsert_player(SCOPE, 222, "Layla", None, "layla@example.com")
    db.ensure_player_stub(SCOPE, 222, "Different Name", None)
    player = db.get_player(SCOPE, 222)
    assert player["name"] == "Layla"
    assert player["email"] == "layla@example.com"


def test_ensure_player_stub_creates_with_no_email():
    player = db.ensure_player_stub(SCOPE, 333, "Stub Player", None)
    assert player["email"] is None
    assert player["balance"] == Decimal("0")


def test_add_transaction_updates_balance_and_records_txn():
    db.upsert_player(SCOPE, 444, "Payer", None, "payer@example.com")
    db.add_transaction(
        SCOPE, 444, Decimal("-43.33"), "2026-08 court share", created_by="system"
    )
    db.add_transaction(SCOPE, 444, Decimal("10"), "sponsor bonus", created_by="admin")

    player = db.get_player(SCOPE, 444)
    assert player["balance"] == Decimal("-33.33")

    txns = db.list_transactions(SCOPE, 444, limit=10)
    assert len(txns) == 2
    descriptions = {t["description"] for t in txns}
    assert descriptions == {"2026-08 court share", "sponsor bonus"}


def test_registration_add_remove_list():
    month = "2026-08"
    db.add_registration(SCOPE, month, 501, added_by="self")
    db.add_registration(SCOPE, month, 502, added_by="admin")

    assert db.is_registered(SCOPE, month, 501) is True
    assert db.is_registered(SCOPE, month, 503) is False

    regs = db.list_registrations(SCOPE, month)
    assert {r["user_id"] for r in regs} == {501, 502}

    db.remove_registration(SCOPE, month, 501)
    assert db.is_registered(SCOPE, month, 501) is False


def test_waitlist_is_fifo_ordered():
    month = "2026-09"
    db.add_waitlist(SCOPE, month, 601)
    db.add_waitlist(SCOPE, month, 602)
    db.add_waitlist(SCOPE, month, 603)

    waitlist = db.list_waitlist(SCOPE, month)
    ordered_ids = [w["user_id"] for w in waitlist]
    assert ordered_ids == [601, 602, 603]


def test_waitlist_remove_entry():
    month = "2026-09"
    db.add_waitlist(SCOPE, month, 701)
    db.add_waitlist(SCOPE, month, 702)

    db.remove_waitlist_entry(SCOPE, month, 701)
    remaining_ids = [w["user_id"] for w in db.list_waitlist(SCOPE, month)]
    assert remaining_ids == [702]


def test_skip_lifecycle():
    date_str = "2026-08-10"
    assert db.get_skip(SCOPE, date_str, 801) is None

    db.add_skip(SCOPE, date_str, 801)
    skip = db.get_skip(SCOPE, date_str, 801)
    assert skip["status"] == "open"
    assert skip["replacement_id"] is None

    db.set_skip_replaced(SCOPE, date_str, 801, 802)
    skip = db.get_skip(SCOPE, date_str, 801)
    assert skip["status"] == "replaced"
    assert skip["replacement_id"] == 802


def test_get_latest_month_picks_max_by_key():
    db.create_month(SCOPE, "2026-06", "Monday", ["2026-06-01"], 100)
    db.create_month(SCOPE, "2026-08", "Monday", ["2026-08-03"], 100)
    db.create_month(SCOPE, "2026-07", "Monday", ["2026-07-06"], 100)

    latest = db.get_latest_month(SCOPE)
    assert latest["month"] == "2026-08"


def test_get_open_month_ignores_finalized():
    db.create_month(SCOPE, "2026-10", "Monday", ["2026-10-05"], 100)
    db.set_month_status(SCOPE, "2026-10", "finalized")
    assert db.get_open_month(SCOPE) is None


def test_delete_month_removes_meta_registrations_and_waitlist():
    month = "2026-11"
    db.create_month(SCOPE, month, "Monday", ["2026-11-02"], 100)
    db.add_registration(SCOPE, month, 901, added_by="self")
    db.add_waitlist(SCOPE, month, 902)

    db.delete_month(SCOPE, month)

    assert db.get_month(SCOPE, month) is None
    assert db.list_registrations(SCOPE, month) == []
    assert db.list_waitlist(SCOPE, month) == []
