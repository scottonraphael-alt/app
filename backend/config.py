import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")
DISCORD_GUILD_ID = os.environ.get("DISCORD_GUILD_ID")
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI")
APP_SESSION_SECRET = os.environ.get("APP_SESSION_SECRET")
DISCORD_HELPER_ROLE_ID = os.environ.get("DISCORD_HELPER_ROLE_ID")
DISCORD_HELPER_ROLE2_ID = os.environ.get("DISCORD_HELPER_ROLE2_ID")
DISCORD_OPERATEUR_ROLE_ID = os.environ.get("DISCORD_OPERATEUR_ROLE_ID")
DISCORD_OPERATEUR_ROLE2_ID = os.environ.get("DISCORD_OPERATEUR_ROLE2_ID")
DISCORD_RESPONSABLE_ROLE_ID = os.environ.get("DISCORD_RESPONSABLE_ROLE_ID")
DISCORD_STAFF_ROLE_ID = os.environ.get("DISCORD_STAFF_ROLE_ID")
DISCORD_ANIMATEUR_ROLE_ID = os.environ.get("DISCORD_ANIMATEUR_ROLE_ID")
DISCORD_ADMIN_ROLE_ID = os.environ.get("DISCORD_ADMIN_ROLE_ID")
DISCORD_TICKET_CATEGORY_ID = os.environ.get("DISCORD_TICKET_CATEGORY_ID")
DISCORD_MODERATION_CHANNEL_TYPES = os.environ.get("DISCORD_MODERATION_CHANNEL_TYPES")
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY")

# --- Modé¶°ration automatique (V3) ---
DISCORD_MONITORED_CHANNELS = [
    channel_id.strip()
    for channel_id in os.environ.get("DISCORD_MONITORED_CHANNELS", "").split(",")
    if channel_id.strip()
]
DISCORD_ALERT_CHANNEL_ID = os.environ.get("DISCORD_ALERT_CHANNEL_ID")
CLASSIFIER_SERVICE_URL = os.environ.get(
    "CLASSIFIER_SERVICE_URL", "http://classifier-service:5000"
)
LLM_SERVICE_URL = os.environ.get("LLM_SERVICE_URL", "http://llm-service:5001")


def missing_discord_bot_settings() -> list[str]:
    required = {
        "DISCORD_GUILD_ID": DISCORD_GUILD_ID,
        "DISCORD_BOT_TOKEN": DISCORD_BOT_TOKEN,
        "DISCORD_HELPER_ROLE_ID": DISCORD_HELPER_ROLE_ID,
        "DISCORD_ADMIN_ROLE_ID": DISCORD_ADMIN_ROLE_ID,
    }
    return [name for name, value in required.items() if not value]


def missing_oauth_settings() -> list[str]:
    required = {
        "DISCORD_CLIENT_ID": DISCORD_CLIENT_ID,
        "DISCORD_CLIENT_SECRET": DISCORD_CLIENT_SECRET,
        "DISCORD_REDIRECT_URI": DISCORD_REDIRECT_URI,
        "APP_SESSION_SECRET": APP_SESSION_SECRET,
        "DISCORD_HELPER_ROLE_ID": DISCORD_HELPER_ROLE_ID,
        "DISCORD_ADMIN_ROLE_ID": DISCORD_ADMIN_ROLE_ID,
    }
    return [name for name, value in required.items() if not value]


def missing_moderation_settings() -> list[str]:
    required = {
        "DISCORD_ALERT_CHANNEL_ID": DISCORD_ALERT_CHANNEL_ID,
    }
    missing = [name for name, value in required.items() if not value]
    if not DISCORD_MONITORED_CHANNELS:
        missing.append("DISCORD_MONITORED_CHANNELS")
    return missing
