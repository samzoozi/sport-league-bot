#!/usr/bin/env python3
"""Delete every item from the bot's DynamoDB table. For local/dev use only.

Usage:
    uv run scripts/wipe_table.py            # prompts for confirmation
    uv run scripts/wipe_table.py --yes       # skips the y/N prompt

Reads TABLE_NAME / AWS_DEFAULT_REGION from .env, same as the bot itself.
Refuses to run against a table whose name doesn't contain "dev" unless you
type the table name back exactly, so it can't casually be pointed at a
production table.
"""

import argparse
import os
import sys

import boto3
from dotenv import load_dotenv

load_dotenv()

TABLE_NAME = os.environ.get("TABLE_NAME", "hangar-sport-bot-dev")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes", action="store_true", help="skip the y/N confirmation prompt"
    )
    args = parser.parse_args()

    table = boto3.resource("dynamodb").Table(TABLE_NAME)

    items = []
    scan_kwargs = {"ProjectionExpression": "PK, SK"}
    while True:
        resp = table.scan(**scan_kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    if not items:
        print(f"Table '{TABLE_NAME}' is already empty.")
        return

    print(f"About to delete {len(items)} item(s) from table '{TABLE_NAME}'.")

    if "dev" not in TABLE_NAME.lower():
        typed = input(
            f"This table name doesn't look like a dev table. Type '{TABLE_NAME}' to confirm: "
        )
        if typed != TABLE_NAME:
            print("Table name did not match — aborting.")
            sys.exit(1)
    elif not args.yes:
        confirm = input("Continue? [y/N] ")
        if confirm.strip().lower() != "y":
            print("Aborted.")
            sys.exit(1)

    with table.batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})

    print(f"Deleted {len(items)} item(s) from '{TABLE_NAME}'.")


if __name__ == "__main__":
    main()
