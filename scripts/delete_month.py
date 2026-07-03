#!/usr/bin/env python3
"""Delete one month's squad/game data, leaving player profiles, balances, and
transaction history untouched. For local/dev use only.

Unlike /deletemonth (bot command, only works on open/non-finalized months to
protect balances), this deletes a month regardless of status — any charges
already posted for it stay on players' balances; only the squad/game records
are removed, so the month key is free to be reused with /newmonth again.

Usage:
    uv run scripts/delete_month.py 2026-07                      # auto-detects the scope if only one match
    uv run scripts/delete_month.py 2026-07 --scope "GROUP#-123456789"
    uv run scripts/delete_month.py 2026-07 --yes                 # skip the y/N prompt
"""

import argparse
import os
import sys

import boto3
from dotenv import load_dotenv

load_dotenv()

TABLE_NAME = os.environ.get("TABLE_NAME", "hangar-sport-bot-dev")


def find_scopes_with_month(table, month: str) -> list[str]:
    scopes = []
    scan_kwargs = {
        "FilterExpression": "SK = :sk",
        "ExpressionAttributeValues": {":sk": f"MONTH#{month}#META"},
    }
    while True:
        resp = table.scan(**scan_kwargs)
        scopes.extend(item["PK"] for item in resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return scopes


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("month", help="Month key, e.g. 2026-07")
    parser.add_argument(
        "--scope",
        help='PK to target, e.g. "GROUP#-123456789". Auto-detected if omitted and unambiguous.',
    )
    parser.add_argument(
        "--yes", action="store_true", help="skip the y/N confirmation prompt"
    )
    args = parser.parse_args()

    table = boto3.resource("dynamodb").Table(TABLE_NAME)

    scope = args.scope
    if scope is None:
        matches = find_scopes_with_month(table, args.month)
        if not matches:
            print(f"No month '{args.month}' found in table '{TABLE_NAME}'.")
            return
        if len(matches) > 1:
            print(
                f"Month '{args.month}' exists in multiple scopes — re-run with --scope:"
            )
            for s in matches:
                print(f"  {s}")
            sys.exit(1)
        scope = matches[0]

    month_item = table.get_item(
        Key={"PK": scope, "SK": f"MONTH#{args.month}#META"}
    ).get("Item")
    if month_item is None:
        print(f"No month '{args.month}' found for scope '{scope}'.")
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
        for prefix in (f"GAME#{date}#SKIP#", f"GAME#{date}#WL#"):
            resp = table.query(
                KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
                ExpressionAttributeValues={":pk": scope, ":prefix": prefix},
                ProjectionExpression="PK, SK",
            )
            keys_to_delete += resp.get("Items", [])

    print(f"Scope: {scope}")
    print(
        f"About to delete {len(keys_to_delete)} item(s) for month '{args.month}' "
        f"(squad, waitlist, skip records — {len(game_dates)} game date(s))."
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
