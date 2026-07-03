from decimal import Decimal

from bot.services.months import (
    current_month,
    game_dates_for_month,
    next_game_date,
    parse_month,
    parse_weekday,
    split_cost,
)


def test_parse_weekday_full_name():
    assert parse_weekday("Monday") == 0
    assert parse_weekday("sunday") == 6


def test_parse_weekday_abbreviation():
    assert parse_weekday("Mon") == 0
    assert parse_weekday("fri") == 4


def test_parse_weekday_invalid():
    assert parse_weekday("Someday") is None


def test_parse_month_valid():
    assert parse_month("2026-08") == (2026, 8)


def test_parse_month_invalid_format():
    assert parse_month("2026/08") is None
    assert parse_month("August 2026") is None


def test_parse_month_invalid_month_number():
    assert parse_month("2026-13") is None


def test_game_dates_for_month_all_mondays():
    # August 2026: Mondays fall on 3, 10, 17, 24, 31
    dates = game_dates_for_month(2026, 8, weekday_index=0)
    assert dates == [
        "2026-08-03",
        "2026-08-10",
        "2026-08-17",
        "2026-08-24",
        "2026-08-31",
    ]


def test_game_dates_for_month_with_skip_dates():
    dates = game_dates_for_month(
        2026, 8, weekday_index=0, skip_dates={"2026-08-03", "2026-08-17"}
    )
    assert dates == ["2026-08-10", "2026-08-24", "2026-08-31"]


def test_game_dates_for_month_no_matching_weekday_left():
    dates = game_dates_for_month(
        2026,
        8,
        weekday_index=0,
        skip_dates={
            "2026-08-03",
            "2026-08-10",
            "2026-08-17",
            "2026-08-24",
            "2026-08-31",
        },
    )
    assert dates == []


def test_split_cost_truncates_not_rounds():
    # 130 / 3 = 43.3333... -> should truncate to 43.33, not round to 43.34
    assert split_cost(Decimal("130"), 3) == Decimal("43.33")


def test_split_cost_exact_division():
    assert split_cost(Decimal("120"), 4) == Decimal("30.00")


def test_split_cost_accepts_non_decimal_input():
    assert split_cost(130, 3) == Decimal("43.33")


def test_next_game_date_picks_earliest_upcoming():
    dates = ["2026-08-03", "2026-08-10", "2026-08-17"]
    assert next_game_date(dates, today="2026-08-05") == "2026-08-10"


def test_next_game_date_today_counts_as_upcoming():
    dates = ["2026-08-03", "2026-08-10"]
    assert next_game_date(dates, today="2026-08-10") == "2026-08-10"


def test_next_game_date_rolls_over_the_day_after():
    # The day after the first date, it should no longer be "next" — the
    # second date takes over automatically, with no special rollover logic.
    dates = ["2026-08-03", "2026-08-10"]
    assert next_game_date(dates, today="2026-08-04") == "2026-08-10"


def test_next_game_date_none_when_all_dates_passed():
    dates = ["2026-08-03", "2026-08-10"]
    assert next_game_date(dates, today="2026-08-11") is None


def test_current_month_prefers_earlier_unresolved_month_over_newer_one():
    # A coordinator finalizes next month's squad while this month's games
    # are still being played — the still-in-progress month must win, not
    # whichever month was created most recently.
    july = {
        "month": "2026-07",
        "status": "finalized",
        "game_dates": ["2026-07-06", "2026-07-13"],
    }
    august = {"month": "2026-08", "status": "finalized", "game_dates": ["2026-08-03"]}

    assert current_month([july, august], today="2026-07-02")["month"] == "2026-07"


def test_current_month_rolls_over_once_earlier_month_is_done():
    july = {
        "month": "2026-07",
        "status": "finalized",
        "game_dates": ["2026-07-06", "2026-07-13"],
    }
    august = {"month": "2026-08", "status": "finalized", "game_dates": ["2026-08-03"]}

    assert current_month([july, august], today="2026-07-14")["month"] == "2026-08"


def test_current_month_ignores_non_finalized_months():
    open_month = {"month": "2026-07", "status": "open", "game_dates": ["2026-07-06"]}
    finalized = {
        "month": "2026-06",
        "status": "finalized",
        "game_dates": ["2026-06-29"],
    }

    assert (
        current_month([open_month, finalized], today="2026-06-25")["month"] == "2026-06"
    )


def test_current_month_falls_back_to_most_recent_when_none_have_upcoming_dates():
    july = {"month": "2026-07", "status": "finalized", "game_dates": ["2026-07-06"]}
    august = {"month": "2026-08", "status": "open", "game_dates": ["2026-08-03"]}

    # Both dates are in the past relative to "today"; no finalized month has
    # an upcoming game, so fall back to whichever month is most recent.
    assert current_month([july, august], today="2026-09-01")["month"] == "2026-08"


def test_current_month_returns_none_for_empty_list():
    assert current_month([]) is None
