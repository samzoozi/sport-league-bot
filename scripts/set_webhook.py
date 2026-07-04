#!/usr/bin/env python3
"""Register the deployed Lambda Function URL as the bot's Telegram webhook,
and push the '/' command menus.

set_bot_commands is normally only invoked automatically by run_polling() in
local dev (bot.app._post_init) — plain Application.initialize() (what the
Lambda handler uses) never calls it, so this script does it explicitly once
after every deploy.

Usage:
    uv run python scripts/set_webhook.py <function-url>
"""

import asyncio
import sys

from telegram import Bot

from bot.app import set_bot_commands
from bot.config import BOT_TOKEN, WEBHOOK_SECRET_TOKEN


async def main(url: str) -> None:
    async with Bot(token=BOT_TOKEN) as bot:
        await bot.set_webhook(url=url, secret_token=WEBHOOK_SECRET_TOKEN)
        await set_bot_commands(bot)
    print(f"Webhook set to {url}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: uv run python scripts/set_webhook.py <function-url>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
