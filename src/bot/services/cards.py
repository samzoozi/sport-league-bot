from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import MAX_PLAYERS, MIN_PLAYERS, STANDARD_PLAYERS


def _month_label(month: str) -> str:
    year, m = month.split("-")
    return date(int(year), int(m), 1).strftime("%B %Y")


def _names(user_ids: list[int], players_by_id: dict[int, dict]) -> list[str]:
    return [players_by_id.get(uid, {}).get("name", f"user {uid}") for uid in user_ids]


def signup_card(
    month_meta: dict,
    registered_ids: list[int],
    waitlist_ids: list[int],
    players_by_id: dict[int, dict],
) -> tuple[str, InlineKeyboardMarkup]:
    month = month_meta["month"]
    dates = ", ".join(month_meta["game_dates"])
    total_cost = month_meta["total_cost"]
    squad_names = _names(registered_ids, players_by_id)
    waitlist_names = _names(waitlist_ids, players_by_id)

    per_player = total_cost / len(registered_ids) if registered_ids else None
    cost_line = f"Total cost: ${total_cost}"
    if per_player is not None:
        cost_line += f" (~${per_player:.2f}/player at current squad size)"

    lines = [
        f"📅 {_month_label(month)} — games on {month_meta['weekday']}s",
        f"Dates: {dates}",
        cost_line,
        "",
        f"Squad ({len(squad_names)}/{MAX_PLAYERS}):",
    ]
    lines += [f"{i}. {name}" for i, name in enumerate(squad_names, 1)] or ["(empty)"]
    lines += ["", f"Waitlist ({len(waitlist_names)}):"]
    lines += [f"{i}. {name}" for i, name in enumerate(waitlist_names, 1)] or ["(empty)"]
    lines += ["", "Tap a button below to join, waitlist, or leave."]

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Join", callback_data=f"signup:join:{month}"),
                InlineKeyboardButton(
                    "⏳ Waitlist", callback_data=f"signup:waitlist:{month}"
                ),
                InlineKeyboardButton("❌ Leave", callback_data=f"signup:leave:{month}"),
            ]
        ]
    )
    return "\n".join(lines), keyboard


def game_card(game_date: str, weekday: str, names: list[str]) -> str:
    count = len(names)
    if count >= STANDARD_PLAYERS:
        status = "✅ Game is on!"
    elif count >= MIN_PLAYERS:
        status = f"⚠️ Only {count} players — game can start if everyone agrees."
    else:
        status = f"❌ Not enough players yet ({count}/{MIN_PLAYERS} minimum)."

    lines = [
        f"🏐 Next game: {weekday}, {game_date}",
        status,
        "",
        f"Players ({count}/{MAX_PLAYERS}):",
    ]
    lines += [f"{i}. {name}" for i, name in enumerate(sorted(names), 1)] or ["(none)"]
    return "\n".join(lines)
