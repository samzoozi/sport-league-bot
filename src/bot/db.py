from datetime import UTC, datetime
from decimal import Decimal

import boto3
from boto3.dynamodb.types import TypeSerializer

from bot.config import TABLE_NAME

_resource = None
_low_level_client = None
_serializer = TypeSerializer()


def table():
    global _resource
    if _resource is None:
        _resource = boto3.resource("dynamodb")
    return _resource.Table(TABLE_NAME)


def _client():
    # A plain low-level client, not resource().meta.client — the latter has the
    # resource layer's auto-serialization hooks attached, which double-wrap
    # already-typed AttributeValue dicts (e.g. {"N": "-5"}) into a MAP.
    global _low_level_client
    if _low_level_client is None:
        _low_level_client = boto3.client("dynamodb")
    return _low_level_client


def _now() -> str:
    return datetime.now(UTC).isoformat()


def player_sk(user_id: int) -> str:
    return f"PLAYER#{user_id}#PROFILE"


def player_txn_sk(user_id: int, ts: str | None = None) -> str:
    return f"PLAYER#{user_id}#TXN#{ts or _now()}"


def month_meta_sk(month: str) -> str:
    return f"MONTH#{month}#META"


def registration_sk(month: str, user_id: int) -> str:
    return f"MONTH#{month}#REG#{user_id}"


def waitlist_sk(date: str, user_id: int, ts: str | None = None) -> str:
    return f"GAME#{date}#WL#{ts or _now()}#{user_id}"


def skip_sk(date: str, user_id: int) -> str:
    return f"GAME#{date}#SKIP#{user_id}"


def extra_sk(date: str, user_id: int) -> str:
    return f"GAME#{date}#EXTRA#{user_id}"


def get_group(scope: str) -> dict | None:
    resp = table().get_item(Key={"PK": scope, "SK": "META"})
    return resp.get("Item")


def create_group(scope: str, title: str, weekday: str) -> None:
    table().put_item(
        Item={
            "PK": scope,
            "SK": "META",
            "item_type": "GROUP",
            "title": title,
            "weekday": weekday,
            "created_at": _now(),
        }
    )


def set_timezone(scope: str, timezone: str) -> None:
    table().update_item(
        Key={"PK": scope, "SK": "META"},
        UpdateExpression="SET #tz = :tz",
        ExpressionAttributeNames={"#tz": "timezone"},
        ExpressionAttributeValues={":tz": timezone},
    )


def get_player(scope: str, user_id: int) -> dict | None:
    resp = table().get_item(Key={"PK": scope, "SK": player_sk(user_id)})
    return resp.get("Item")


def upsert_player(
    scope: str, user_id: int, name: str, username: str | None, email: str | None
) -> None:
    table().update_item(
        Key={"PK": scope, "SK": player_sk(user_id)},
        UpdateExpression=(
            "SET item_type = :t, user_id = :uid, #n = :name, username = :username, "
            "email = :email, balance = if_not_exists(balance, :zero)"
        ),
        ExpressionAttributeNames={"#n": "name"},
        ExpressionAttributeValues={
            ":t": "PROFILE",
            ":uid": user_id,
            ":name": name,
            ":username": username,
            ":email": email,
            ":zero": Decimal(0),
        },
    )


def ensure_player_stub(
    scope: str, user_id: int, name: str, username: str | None
) -> dict:
    player = get_player(scope, user_id)
    if player is not None:
        return player

    item = {
        "PK": scope,
        "SK": player_sk(user_id),
        "item_type": "PROFILE",
        "user_id": user_id,
        "name": name,
        "username": username,
        "email": None,
        "balance": Decimal(0),
    }
    table().put_item(Item=item)
    return item


def list_players(scope: str) -> list[dict]:
    resp = table().query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        FilterExpression="item_type = :t",
        ExpressionAttributeValues={
            ":pk": scope,
            ":prefix": "PLAYER#",
            ":t": "PROFILE",
        },
    )
    return resp.get("Items", [])


def list_transactions(scope: str, user_id: int, limit: int = 5) -> list[dict]:
    resp = table().query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={
            ":pk": scope,
            ":prefix": f"PLAYER#{user_id}#TXN#",
        },
        ScanIndexForward=False,
        Limit=limit,
    )
    return resp.get("Items", [])


def create_month(
    scope: str, month: str, weekday: str, game_dates: list[str], total_cost
) -> None:
    table().put_item(
        Item={
            "PK": scope,
            "SK": month_meta_sk(month),
            "item_type": "MONTH",
            "month": month,
            "weekday": weekday,
            "game_dates": game_dates,
            "total_cost": Decimal(str(total_cost)),
            "cost_per_player": None,
            "status": "open",
            "signup_message_id": None,
        }
    )


def _normalize_month(item: dict | None) -> dict | None:
    # DynamoDB returns all numbers as Decimal; signup_message_id is a Telegram
    # message ID and must be a plain int wherever it's used against the Bot API.
    if item is not None and item.get("signup_message_id") is not None:
        item["signup_message_id"] = int(item["signup_message_id"])
    return item


def get_month(scope: str, month: str) -> dict | None:
    resp = table().get_item(Key={"PK": scope, "SK": month_meta_sk(month)})
    return _normalize_month(resp.get("Item"))


def get_open_month(scope: str) -> dict | None:
    resp = table().query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        FilterExpression="item_type = :t AND #s = :open",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":pk": scope,
            ":prefix": "MONTH#",
            ":t": "MONTH",
            ":open": "open",
        },
    )
    items = resp.get("Items", [])
    return _normalize_month(items[0]) if items else None


def set_month_signup_message(scope: str, month: str, message_id: int) -> None:
    table().update_item(
        Key={"PK": scope, "SK": month_meta_sk(month)},
        UpdateExpression="SET signup_message_id = :m",
        ExpressionAttributeValues={":m": message_id},
    )


def set_month_status(scope: str, month: str, status: str) -> None:
    table().update_item(
        Key={"PK": scope, "SK": month_meta_sk(month)},
        UpdateExpression="SET #s = :status",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": status},
    )


def set_month_cost_per_player(scope: str, month: str, cost_per_player) -> None:
    table().update_item(
        Key={"PK": scope, "SK": month_meta_sk(month)},
        UpdateExpression="SET cost_per_player = :c",
        ExpressionAttributeValues={":c": Decimal(str(cost_per_player))},
    )


def add_registration(scope: str, month: str, user_id: int, added_by: str) -> None:
    table().put_item(
        Item={
            "PK": scope,
            "SK": registration_sk(month, user_id),
            "item_type": "REG",
            "user_id": user_id,
            "joined_at": _now(),
            "added_by": added_by,
        }
    )


def remove_registration(scope: str, month: str, user_id: int) -> None:
    table().delete_item(Key={"PK": scope, "SK": registration_sk(month, user_id)})


def is_registered(scope: str, month: str, user_id: int) -> bool:
    resp = table().get_item(Key={"PK": scope, "SK": registration_sk(month, user_id)})
    return "Item" in resp


def list_registrations(scope: str, month: str) -> list[dict]:
    resp = table().query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={
            ":pk": scope,
            ":prefix": f"MONTH#{month}#REG#",
        },
    )
    # The SK sorts by user_id, not join time — always re-sort by joined_at so
    # callers see true join order (e.g. leaving and rejoining moves someone
    # to the back of the line, not back to their user_id's fixed rank).
    return sorted(resp.get("Items", []), key=lambda r: r["joined_at"])


def add_waitlist(scope: str, date: str, user_id: int) -> None:
    table().put_item(
        Item={
            "PK": scope,
            "SK": waitlist_sk(date, user_id),
            "item_type": "WAITLIST",
            "user_id": user_id,
            "joined_at": _now(),
        }
    )


def remove_waitlist_entry(scope: str, date: str, user_id: int) -> None:
    for entry in list_waitlist(scope, date):
        if entry["user_id"] == user_id:
            table().delete_item(Key={"PK": scope, "SK": entry["SK"]})


def list_waitlist(scope: str, date: str) -> list[dict]:
    resp = table().query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={
            ":pk": scope,
            ":prefix": f"GAME#{date}#WL#",
        },
    )
    return resp.get("Items", [])


def add_transaction(
    scope: str, user_id: int, amount, description: str, created_by: str
) -> None:
    amount_dec = Decimal(str(amount))
    txn_item = {
        "PK": scope,
        "SK": player_txn_sk(user_id),
        "item_type": "TXN",
        "user_id": user_id,
        "amount": amount_dec,
        "description": description,
        "created_by": created_by,
    }
    _client().transact_write_items(
        TransactItems=[
            {
                "Put": {
                    "TableName": TABLE_NAME,
                    "Item": {k: _serializer.serialize(v) for k, v in txn_item.items()},
                }
            },
            {
                "Update": {
                    "TableName": TABLE_NAME,
                    "Key": {
                        "PK": _serializer.serialize(scope),
                        "SK": _serializer.serialize(player_sk(user_id)),
                    },
                    "UpdateExpression": "ADD balance :amt",
                    "ExpressionAttributeValues": {
                        ":amt": _serializer.serialize(amount_dec)
                    },
                }
            },
        ]
    )


def list_months(scope: str) -> list[dict]:
    resp = table().query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        FilterExpression="item_type = :t",
        ExpressionAttributeValues={
            ":pk": scope,
            ":prefix": "MONTH#",
            ":t": "MONTH",
        },
    )
    return [_normalize_month(item) for item in resp.get("Items", [])]


def add_skip(scope: str, date: str, user_id: int) -> None:
    table().put_item(
        Item={
            "PK": scope,
            "SK": skip_sk(date, user_id),
            "item_type": "SKIP",
            "user_id": user_id,
            "date": date,
            "status": "open",
            "replacement_id": None,
            "vacated_by": user_id,
            "created_at": _now(),
        }
    )


def _normalize_skip(item: dict | None) -> dict | None:
    # vacated_by was added after some skip records already existed in
    # production — default it to the record's own owner so reading an old
    # row behaves exactly like it did before the field existed.
    if item is not None:
        item.setdefault("vacated_by", item["user_id"])
    return item


def get_skip(scope: str, date: str, user_id: int) -> dict | None:
    resp = table().get_item(Key={"PK": scope, "SK": skip_sk(date, user_id)})
    return _normalize_skip(resp.get("Item"))


def set_skip_replaced(
    scope: str, date: str, skipper_id: int, replacement_id: int
) -> None:
    table().update_item(
        Key={"PK": scope, "SK": skip_sk(date, skipper_id)},
        UpdateExpression="SET #s = :replaced, replacement_id = :r",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":replaced": "replaced", ":r": replacement_id},
    )


def reopen_skip(scope: str, date: str, owner_id: int, vacated_by: int) -> None:
    """Vacate a spot that's currently held (by the original registrant or a
    replacement) so the offer chain can restart — used when whoever's
    currently playing `date` backs out via /skip."""
    table().update_item(
        Key={"PK": scope, "SK": skip_sk(date, owner_id)},
        UpdateExpression="SET #s = :open, replacement_id = :none, vacated_by = :v",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":open": "open", ":none": None, ":v": vacated_by},
    )


def get_occupied_skip(scope: str, date: str, user_id: int) -> dict | None:
    """Find the skip record whose spot `user_id` currently holds as a
    replacement (not the original registrant) for `date`, if any."""
    for skip in list_skips_for_date(scope, date):
        if skip["status"] == "replaced" and int(skip["replacement_id"]) == user_id:
            return skip
    return None


def list_skips_for_date(scope: str, date: str) -> list[dict]:
    resp = table().query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={
            ":pk": scope,
            ":prefix": f"GAME#{date}#SKIP#",
        },
    )
    return [_normalize_skip(item) for item in resp.get("Items", [])]


def add_extra_attendee(scope: str, date: str, user_id: int) -> None:
    """Add someone to a specific game who isn't tied to any registration or
    skip — e.g. an admin-added guest, independent of the squad/skip system."""
    table().put_item(
        Item={
            "PK": scope,
            "SK": extra_sk(date, user_id),
            "item_type": "EXTRA",
            "user_id": user_id,
            "date": date,
            "created_at": _now(),
        }
    )


def remove_extra_attendee(scope: str, date: str, user_id: int) -> None:
    table().delete_item(Key={"PK": scope, "SK": extra_sk(date, user_id)})


def get_extra_attendee(scope: str, date: str, user_id: int) -> dict | None:
    resp = table().get_item(Key={"PK": scope, "SK": extra_sk(date, user_id)})
    return resp.get("Item")


def list_extra_attendees(scope: str, date: str) -> list[dict]:
    resp = table().query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={
            ":pk": scope,
            ":prefix": f"GAME#{date}#EXTRA#",
        },
    )
    return resp.get("Items", [])


def delete_month(scope: str, month: str) -> None:
    # Only ever called on an open (non-finalized) month, which can't have any
    # per-game waitlist entries yet (those only exist post-finalize) — so
    # there's nothing waitlist-related to clean up here.
    table().delete_item(Key={"PK": scope, "SK": month_meta_sk(month)})
    for r in list_registrations(scope, month):
        table().delete_item(Key={"PK": scope, "SK": r["SK"]})
