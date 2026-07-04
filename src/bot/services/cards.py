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
    players_by_id: dict[int, dict],
) -> tuple[str, InlineKeyboardMarkup | None]:
    month = month_meta["month"]
    dates = ", ".join(month_meta["game_dates"])
    total_cost = month_meta["total_cost"]
    squad_names = _names(registered_ids, players_by_id)
    finalized = month_meta["status"] == "finalized"

    cost_per_player = month_meta.get("cost_per_player")
    if finalized and cost_per_player is not None:
        cost_line = f"💰 Total cost: ${total_cost} (${cost_per_player}/player, charged)"
    else:
        per_player = total_cost / len(registered_ids) if registered_ids else None
        cost_line = f"💰 Total cost: ${total_cost}"
        if per_player is not None:
            cost_line += f" (~${per_player:.2f}/player at current squad size)"

    header = (
        f"🔒 {_month_label(month)} — FINALIZED"
        if finalized
        else f"📅 {_month_label(month)}"
    )
    lines = [
        f"{header} — games on {month_meta['weekday']}s",
        f"🗓️ Dates: {dates}",
        cost_line,
        "",
        f"👥 {'Final squad' if finalized else 'Squad'} ({len(squad_names)}/{MAX_PLAYERS}):",
    ]
    lines += [f"{i}. {name}" for i, name in enumerate(squad_names, 1)] or ["(empty)"]

    if finalized:
        return "\n".join(lines), None

    lines += ["", "👇 Tap a button below to join or decline."]
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Join", callback_data=f"signup:join:{month}"),
                InlineKeyboardButton(
                    "❌ Decline", callback_data=f"signup:leave:{month}"
                ),
            ]
        ]
    )
    return "\n".join(lines), keyboard


def game_card(
    game_date: str,
    weekday: str,
    roster: list[dict],
    players_by_id: dict[int, dict],
) -> str:
    def name_of(user_id: int) -> str:
        return players_by_id.get(user_id, {}).get("name", f"user {user_id}")

    rows = []
    count = 0
    for entry in roster:
        registrant_name = name_of(entry["registrant_id"])
        if not entry["skipped"]:
            row = registrant_name
            count += 1
        elif entry["replacement_id"] is not None:
            row = f"❌ {registrant_name} → {name_of(entry['replacement_id'])}"
            count += 1
        else:
            row = f"❌ {registrant_name} (no replacement yet)"
        rows.append((registrant_name, row))
    rows.sort(key=lambda r: r[0])

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
        f"👥 Players ({count}/{MAX_PLAYERS}):",
    ]
    lines += [f"{i}. {row}" for i, (_, row) in enumerate(rows, 1)] or ["(none)"]
    return "\n".join(lines)
