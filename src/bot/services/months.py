import calendar
import re
from datetime import date
from decimal import ROUND_DOWN, Decimal

MONTH_RE = re.compile(r"^\d{4}-\d{2}$")

WEEKDAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def parse_weekday(text: str) -> int | None:
    text = text.strip().lower()
    for i, name in enumerate(WEEKDAY_NAMES):
        if text == name.lower() or text == name.lower()[:3]:
            return i
    return None


def parse_month(text: str) -> tuple[int, int] | None:
    if not MONTH_RE.match(text):
        return None
    year, month = text.split("-")
    year, month = int(year), int(month)
    if not (1 <= month <= 12):
        return None
    return year, month


def game_dates_for_month(
    year: int, month: int, weekday_index: int, skip_dates: set[str] | None = None
) -> list[str]:
    skip_dates = skip_dates or set()
    _, days_in_month = calendar.monthrange(year, month)
    dates = []
    for day in range(1, days_in_month + 1):
        d = date(year, month, day)
        if d.weekday() == weekday_index and d.isoformat() not in skip_dates:
            dates.append(d.isoformat())
    return dates


def split_cost(total_cost, count: int) -> Decimal:
    """Divide total_cost across count players, truncated (not rounded) to cents."""
    return (Decimal(str(total_cost)) / count).quantize(
        Decimal("0.01"), rounding=ROUND_DOWN
    )


def next_game_date(game_dates: list[str], today: str | None = None) -> str | None:
    """The earliest date in game_dates that hasn't happened yet, or None if
    every date in the list is in the past."""
    today = today or date.today().isoformat()
    upcoming = [d for d in game_dates if d >= today]
    return upcoming[0] if upcoming else None


def current_month(months: list[dict], today: str | None = None) -> dict | None:
    """Which month record "owns" the next game right now.

    Multiple months can legitimately coexist — e.g. a coordinator finalizes
    next month's squad while this month's games are still being played. The
    month that matters for /nextgame, /skip, /waitlist/addtowaitlist, and /games is
    whichever finalized month has the earliest still-upcoming game date, not
    whichever month was created most recently. If no finalized month has any
    upcoming date left, fall back to the most recently created month overall
    (e.g. a month still in open signup, or the last one ever played)."""
    today = today or date.today().isoformat()

    candidates = []
    for m in months:
        if m["status"] != "finalized":
            continue
        nxt = next_game_date(m["game_dates"], today)
        if nxt is not None:
            candidates.append((nxt, m))

    if candidates:
        candidates.sort(key=lambda pair: pair[0])
        return candidates[0][1]

    return max(months, key=lambda m: m["month"]) if months else None


def month_for_date(months: list[dict], game_date: str) -> dict | None:
    """Which month's schedule a specific game date belongs to, regardless of
    whether it's the "current" one — for admin commands that target an
    arbitrary past/future game by date rather than always the next match."""
    for m in months:
        if game_date in m["game_dates"]:
            return m
    return None
