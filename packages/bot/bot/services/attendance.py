from bot import db


def game_roster(scope: str, month: str, date: str) -> list[dict]:
    """Every original squad member's status for `date`, plus anyone added
    directly to this one game (via /addplayer, independent of the squad):
    `registrant_id` is always the original registrant (or the extra
    attendee's own id), `skipped` says whether they backed out, and
    `replacement_id` is who (if anyone) is currently covering their spot.
    Used to render the full squad in game cards — unlike attendees_for_date,
    a skipped-and-unfilled member still gets an entry."""
    roster = []
    for reg in db.list_registrations(scope, month):
        user_id = int(reg["user_id"])
        skip = db.get_skip(scope, date, user_id)
        replacement_id = None
        if skip is not None and skip["status"] == "replaced":
            replacement_id = int(skip["replacement_id"])
        roster.append(
            {
                "registrant_id": user_id,
                "skipped": skip is not None,
                "replacement_id": replacement_id,
            }
        )
    for extra in db.list_extra_attendees(scope, date):
        roster.append(
            {
                "registrant_id": int(extra["user_id"]),
                "skipped": False,
                "replacement_id": None,
            }
        )
    return roster


def attendees_for_date(scope: str, month: str, date: str) -> list[int]:
    """Who's actually playing on `date`: registered squad members minus anyone
    with an unfilled skip, plus whoever replaced a skipped spot."""
    attendees = []
    for entry in game_roster(scope, month, date):
        if not entry["skipped"]:
            attendees.append(entry["registrant_id"])
        elif entry["replacement_id"] is not None:
            attendees.append(entry["replacement_id"])
    return attendees
