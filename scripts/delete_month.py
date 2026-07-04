#!/usr/bin/env python3
"""Delete one month's squad/game data, leaving player profiles, balances, and
transaction history untouched. For local/dev use only.

Unlike /deletemonth (bot command, only works on open/non-finalized months to
protect balances), this deletes a month regardless of status — any charges
already posted for it stay on players' balances; only the squad/game records
are removed, so the month key is free to be reused with /newmonth again.

Usage:
    uv run scripts/delete_month.py dev -5470494442 2026-07
    uv run scripts/delete_month.py prod -5470494442 2026-07 --yes
    uv run scripts/delete_month.py dev "GROUP#-5470494442#TOPIC#123" 2026-07
"""

import argparse
import sys

import boto3
from dotenv import load_dotenv

load_dotenv()

TABLE_NAMES = {
    "dev": "hangar-sport-bot-dev",
    "prod": "hangar-sport-bot",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("table", choices=TABLE_NAMES, help="which table to target")
    parser.add_argument(
        "group_id",
        help='the group\'s chat_id (e.g. "-5470494442"), or a full scope '
        '(e.g. "GROUP#-5470494442#TOPIC#123") to target one forum topic',
    )
    parser.add_argument("month", help="Month key, e.g. 2026-07")
    parser.add_argument(
        "--yes", action="store_true", help="skip the y/N confirmation prompt"
    )
    args = parser.parse_args()

    table_name = TABLE_NAMES[args.table]
    scope = (
        args.group_id
        if args.group_id.startswith("GROUP#")
        else f"GROUP#{args.group_id}"
    )
    table = boto3.resource("dynamodb").Table(table_name)

    month_item = table.get_item(
        Key={"PK": scope, "SK": f"MONTH#{args.month}#META"}
    ).get("Item")
    if month_item is None:
        print(
            f"No month '{args.month}' found for scope '{scope}' in table '{table_name}'."
        )
        return

    game_dates = month_item.get("game_dates", [])

    keys_to_delete = [{"PK": scope, "SK": f"MONTH#{args.month}#META"}]

    resp = table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={":pk": scope, ":prefix": f"MONTH#{args.month}#REG#"},
        ProjectionExpression="PK, SK",
    )
    keys_to_delete += resp.get("Items", [])

    for date in game_dates:
        for prefix in (f"GAME#{date}#SKIP#", f"GAME#{date}#WL#", f"GAME#{date}#EXTRA#"):
            resp = table.query(
                KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
                ExpressionAttributeValues={":pk": scope, ":prefix": prefix},
                ProjectionExpression="PK, SK",
            )
            keys_to_delete += resp.get("Items", [])

    print(f"Table: {table_name}")
    print(f"Scope: {scope}")
    print(
        f"About to delete {len(keys_to_delete)} item(s) for month '{args.month}' "
        f"(squad, waitlist, skip, extra-attendee records — {len(game_dates)} game date(s))."
    )
    print("Player profiles, balances, and transaction history will NOT be touched.")

    if not args.yes:
        confirm = input("Continue? [y/N] ")
        if confirm.strip().lower() != "y":
            print("Aborted.")
            sys.exit(1)

    with table.batch_writer() as batch:
        for key in keys_to_delete:
            batch.delete_item(Key={"PK": key["PK"], "SK": key["SK"]})

    print(f"Deleted {len(keys_to_delete)} item(s) for month '{args.month}'.")


if __name__ == "__main__":
    main()
