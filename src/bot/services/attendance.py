from bot import db


def attendees_for_date(scope: str, month: str, date: str) -> list[int]:
    """Who's actually playing on `date`: registered squad members minus anyone
    with an unfilled skip, plus whoever replaced a skipped spot."""
    attendees = []
    for reg in db.list_registrations(scope, month):
        user_id = int(reg["user_id"])
        skip = db.get_skip(scope, date, user_id)
        if skip is None:
            attendees.append(user_id)
        elif skip["status"] == "replaced":
            attendees.append(int(skip["replacement_id"]))
    return attendees
