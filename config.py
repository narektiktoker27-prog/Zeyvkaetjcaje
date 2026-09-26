import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID_RAW = os.getenv("OWNER_ID", "").strip()
DB_PATH = os.getenv("DB_PATH", "bot.db").strip() or "bot.db"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required.")

try:
    OWNER_ID = int(OWNER_ID_RAW)
except ValueError as exc:
    raise RuntimeError("OWNER_ID must be a Telegram numeric user ID.") from exc

if OWNER_ID <= 0:
    raise RuntimeError("OWNER_ID must be a positive Telegram user ID.")
