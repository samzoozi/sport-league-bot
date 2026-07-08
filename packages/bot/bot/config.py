import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
TABLE_NAME = os.environ.get("TABLE_NAME", "hangar-sport-bot-dev")
WEBHOOK_SECRET_TOKEN = os.environ.get("WEBHOOK_SECRET_TOKEN")

MIN_PLAYERS = int(os.environ.get("MIN_PLAYERS", 10))
STANDARD_PLAYERS = int(os.environ.get("STANDARD_PLAYERS", 12))
MAX_PLAYERS = int(os.environ.get("MAX_PLAYERS", 14))

# Comma-separated chat IDs the bot is allowed to operate in, e.g. "-100123,-100456".
# Unset means no restriction (any group can add and use the bot).
_allowed_chat_ids_raw = os.environ.get("ALLOWED_CHAT_IDS", "").strip()
ALLOWED_CHAT_IDS = (
    {int(chat_id) for chat_id in _allowed_chat_ids_raw.split(",") if chat_id.strip()}
    if _allowed_chat_ids_raw
    else None
)
