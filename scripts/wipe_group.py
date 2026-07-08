#!/usr/bin/env python3
"""Delete every record for one group (or one forum topic) — squad/game data,
balances, transaction history, and player profiles included. For local/dev
use only; the prod table is supported for cleaning up a group that's leaving
the league, but there's no going back.

Usage:
    uv run scripts/wipe_group.py dev -5470494442
    uv run scripts/wipe_group.py prod -5470494442 --yes
    uv run scripts/wipe_group.py dev "GROUP#-5470494442#TOPIC#123"
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

    keys_to_delete = []
    query_kwargs = {
        "KeyConditionExpression": "PK = :pk",
        "ExpressionAttributeValues": {":pk": scope},
        "ProjectionExpression": "PK, SK",
    }
    while True:
        resp = table.query(**query_kwargs)
        keys_to_delete += resp.get("Items", [])
        if "LastEvaluatedKey" not in resp:
            break
        query_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    if not keys_to_delete:
        print(f"No records found for scope '{scope}' in table '{table_name}'.")
        return

    print(f"Table: {table_name}")
    print(f"Scope: {scope}")
    print(
        f"About to delete {len(keys_to_delete)} item(s) — squad/game data, "
        "balances, transaction history, AND player profiles."
    )
    print("This cannot be undone.")

    if not args.yes:
        confirm = input("Continue? [y/N] ")
        if confirm.strip().lower() != "y":
            print("Aborted.")
            sys.exit(1)

    with table.batch_writer() as batch:
        for key in keys_to_delete:
            batch.delete_item(Key={"PK": key["PK"], "SK": key["SK"]})

    print(f"Deleted {len(keys_to_delete)} item(s) for scope '{scope}'.")


if __name__ == "__main__":
    main()
