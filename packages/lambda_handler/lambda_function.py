import asyncio
import json

from telegram import Update

from bot.app import build_application
from bot.config import WEBHOOK_SECRET_TOKEN

application = build_application()


async def _process(body: dict) -> None:
    # PTB's own recommended pattern for serverless use: initialize()/shutdown()
    # once per invocation via the async context manager, rather than trying to
    # persist an event loop across warm Lambda invocations.
    async with application:
        update = Update.de_json(body, application.bot)
        await application.process_update(update)


def handler(event, context):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if headers.get("x-telegram-bot-api-secret-token") != WEBHOOK_SECRET_TOKEN:
        return {"statusCode": 403, "body": "forbidden"}

    body = json.loads(event.get("body") or "{}")
    asyncio.run(_process(body))
    return {"statusCode": 200, "body": ""}
