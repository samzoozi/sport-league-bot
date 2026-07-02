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


def group_pk(chat_id: int) -> str:
    return f"GROUP#{chat_id}"


def player_sk(user_id: int) -> str:
    return f"PLAYER#{user_id}#PROFILE"


def player_txn_sk(user_id: int, ts: str | None = None) -> str:
    return f"PLAYER#{user_id}#TXN#{ts or _now()}"


def month_meta_sk(month: str) -> str:
    return f"MONTH#{month}#META"


def registration_sk(month: str, user_id: int) -> str:
    return f"MONTH#{month}#REG#{user_id}"


def waitlist_sk(month: str, user_id: int, ts: str | None = None) -> str:
    return f"MONTH#{month}#WL#{ts or _now()}#{user_id}"


def skip_sk(date: str, user_id: int) -> str:
    return f"GAME#{date}#SKIP#{user_id}"


def get_group(chat_id: int) -> dict | None:
    resp = table().get_item(Key={"PK": group_pk(chat_id), "SK": "META"})
    return resp.get("Item")


def create_group(chat_id: int, title: str, weekday: str) -> None:
    table().put_item(
        Item={
            "PK": group_pk(chat_id),
            "SK": "META",
            "item_type": "GROUP",
            "title": title,
            "weekday": weekday,
            "created_at": _now(),
        }
    )


def get_player(chat_id: int, user_id: int) -> dict | None:
    resp = table().get_item(Key={"PK": group_pk(chat_id), "SK": player_sk(user_id)})
    return resp.get("Item")


def upsert_player(
    chat_id: int, user_id: int, name: str, username: str | None, email: str
) -> None:
    table().update_item(
        Key={"PK": group_pk(chat_id), "SK": player_sk(user_id)},
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
    chat_id: int, user_id: int, name: str, username: str | None
) -> dict:
    player = get_player(chat_id, user_id)
    if player is not None:
        return player

    item = {
        "PK": group_pk(chat_id),
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


def list_players(chat_id: int) -> list[dict]:
    resp = table().query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        FilterExpression="item_type = :t",
        ExpressionAttributeValues={
            ":pk": group_pk(chat_id),
            ":prefix": "PLAYER#",
            ":t": "PROFILE",
        },
    )
    return resp.get("Items", [])


def list_transactions(chat_id: int, user_id: int, limit: int = 5) -> list[dict]:
    resp = table().query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={
            ":pk": group_pk(chat_id),
            ":prefix": f"PLAYER#{user_id}#TXN#",
        },
        ScanIndexForward=False,
        Limit=limit,
    )
    return resp.get("Items", [])


def create_month(
    chat_id: int, month: str, weekday: str, game_dates: list[str], total_cost
) -> None:
    table().put_item(
        Item={
            "PK": group_pk(chat_id),
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


def get_month(chat_id: int, month: str) -> dict | None:
    resp = table().get_item(Key={"PK": group_pk(chat_id), "SK": month_meta_sk(month)})
    return _normalize_month(resp.get("Item"))


def get_open_month(chat_id: int) -> dict | None:
    resp = table().query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        FilterExpression="item_type = :t AND #s = :open",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":pk": group_pk(chat_id),
            ":prefix": "MONTH#",
            ":t": "MONTH",
            ":open": "open",
        },
    )
    items = resp.get("Items", [])
    return _normalize_month(items[0]) if items else None


def set_month_signup_message(chat_id: int, month: str, message_id: int) -> None:
    table().update_item(
        Key={"PK": group_pk(chat_id), "SK": month_meta_sk(month)},
        UpdateExpression="SET signup_message_id = :m",
        ExpressionAttributeValues={":m": message_id},
    )


def set_month_status(chat_id: int, month: str, status: str) -> None:
    table().update_item(
        Key={"PK": group_pk(chat_id), "SK": month_meta_sk(month)},
        UpdateExpression="SET #s = :status",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": status},
    )


def set_month_cost_per_player(chat_id: int, month: str, cost_per_player) -> None:
    table().update_item(
        Key={"PK": group_pk(chat_id), "SK": month_meta_sk(month)},
        UpdateExpression="SET cost_per_player = :c",
        ExpressionAttributeValues={":c": Decimal(str(cost_per_player))},
    )


def add_registration(chat_id: int, month: str, user_id: int, added_by: str) -> None:
    table().put_item(
        Item={
            "PK": group_pk(chat_id),
            "SK": registration_sk(month, user_id),
            "item_type": "REG",
            "user_id": user_id,
            "joined_at": _now(),
            "added_by": added_by,
        }
    )


def remove_registration(chat_id: int, month: str, user_id: int) -> None:
    table().delete_item(
        Key={"PK": group_pk(chat_id), "SK": registration_sk(month, user_id)}
    )


def is_registered(chat_id: int, month: str, user_id: int) -> bool:
    resp = table().get_item(
        Key={"PK": group_pk(chat_id), "SK": registration_sk(month, user_id)}
    )
    return "Item" in resp


def list_registrations(chat_id: int, month: str) -> list[dict]:
    resp = table().query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={
            ":pk": group_pk(chat_id),
            ":prefix": f"MONTH#{month}#REG#",
        },
    )
    return resp.get("Items", [])


def add_waitlist(chat_id: int, month: str, user_id: int) -> None:
    table().put_item(
        Item={
            "PK": group_pk(chat_id),
            "SK": waitlist_sk(month, user_id),
            "item_type": "WAITLIST",
            "user_id": user_id,
            "joined_at": _now(),
        }
    )


def remove_waitlist_entry(chat_id: int, month: str, user_id: int) -> None:
    for entry in list_waitlist(chat_id, month):
        if entry["user_id"] == user_id:
            table().delete_item(Key={"PK": group_pk(chat_id), "SK": entry["SK"]})


def list_waitlist(chat_id: int, month: str) -> list[dict]:
    resp = table().query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={
            ":pk": group_pk(chat_id),
            ":prefix": f"MONTH#{month}#WL#",
        },
    )
    return resp.get("Items", [])


def add_transaction(
    chat_id: int, user_id: int, amount, description: str, created_by: str
) -> None:
    amount_dec = Decimal(str(amount))
    txn_item = {
        "PK": group_pk(chat_id),
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
                        "PK": _serializer.serialize(group_pk(chat_id)),
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


def get_latest_month(chat_id: int) -> dict | None:
    resp = table().query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        FilterExpression="item_type = :t",
        ExpressionAttributeValues={
            ":pk": group_pk(chat_id),
            ":prefix": "MONTH#",
            ":t": "MONTH",
        },
    )
    items = resp.get("Items", [])
    if not items:
        return None
    return _normalize_month(max(items, key=lambda item: item["month"]))


def add_skip(chat_id: int, date: str, user_id: int) -> None:
    table().put_item(
        Item={
            "PK": group_pk(chat_id),
            "SK": skip_sk(date, user_id),
            "item_type": "SKIP",
            "user_id": user_id,
            "date": date,
            "status": "open",
            "replacement_id": None,
            "created_at": _now(),
        }
    )


def get_skip(chat_id: int, date: str, user_id: int) -> dict | None:
    resp = table().get_item(Key={"PK": group_pk(chat_id), "SK": skip_sk(date, user_id)})
    return resp.get("Item")


def set_skip_replaced(
    chat_id: int, date: str, skipper_id: int, replacement_id: int
) -> None:
    table().update_item(
        Key={"PK": group_pk(chat_id), "SK": skip_sk(date, skipper_id)},
        UpdateExpression="SET #s = :replaced, replacement_id = :r",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":replaced": "replaced", ":r": replacement_id},
    )


def list_skips_for_date(chat_id: int, date: str) -> list[dict]:
    resp = table().query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={
            ":pk": group_pk(chat_id),
            ":prefix": f"GAME#{date}#SKIP#",
        },
    )
    return resp.get("Items", [])


def delete_month(chat_id: int, month: str) -> None:
    table().delete_item(Key={"PK": group_pk(chat_id), "SK": month_meta_sk(month)})
    for r in list_registrations(chat_id, month):
        table().delete_item(Key={"PK": group_pk(chat_id), "SK": r["SK"]})
    for w in list_waitlist(chat_id, month):
        table().delete_item(Key={"PK": group_pk(chat_id), "SK": w["SK"]})
