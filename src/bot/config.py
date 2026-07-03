import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
TABLE_NAME = os.environ.get("TABLE_NAME", "hangar-sport-bot-dev")
WEBHOOK_SECRET_TOKEN = os.environ.get("WEBHOOK_SECRET_TOKEN")

MIN_PLAYERS = int(os.environ.get("MIN_PLAYERS", 10))
STANDARD_PLAYERS = int(os.environ.get("STANDARD_PLAYERS", 12))
MAX_PLAYERS = int(os.environ.get("MAX_PLAYERS", 14))
