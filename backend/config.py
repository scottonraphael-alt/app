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
DISCORD_ADMIN_ROLE_ID = os.environ.get("DISCORD_ADMIN_ROLE_ID")
DISCORD_TICKET_CATEGORY_ID = os.environ.get("DISCORD_TICKET_CATEGORY_ID")
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY")
DISCORD_STAFF_ROLE_ID = os.environ.get("DISCORD_STAFF_ROLE_ID")
DISCORD_RESPONSABLE_ROLE_ID = os.environ.get("DISCORD_RESPONSABLE_ROLE_ID")
DISCORD_HELPER_ROLE2_ID = os.environ.get("DISCORD_HELPER_ROLE2_ID")
DISCORD_ANIMATEUR_ROLE_ID = os.getenv("DISCORD_ANIMATEUR_ROLE_ID", "")
DISCORD_OPERATEUR_ROLE_ID = os.getenv("DISCORD_OPERATEUR_ROLE_ID", "")
DISCORD_OPERATEUR_ROLE2_ID = os.getenv("DISCORD_OPERATEUR_ROLE2_ID", "")


def missing_discord_bot_settings() -> list[str]:
    required = {
        "DISCORD_GUILD_ID": DISCORD_GUILD_ID,
        "DISCORD_BOT_TOKEN": DISCORD_BOT_TOKEN,
        "DISCORD_HELPER_ROLE_ID": DISCORD_HELPER_ROLE_ID,
        "DISCORD_ADMIN_ROLE_ID": DISCORD_ADMIN_ROLE_ID,
        "DISCORD_TICKET_CATEGORY_ID": DISCORD_TICKET_CATEGORY_ID,
    }
    return [name for name, value in required.items() if not value]

import os

VALID_SANCTION_TYPES = {"avertissement", "bannissement", "kick", "rappel_a_lordre"}


def parse_moderation_channels(raw: str) -> dict[int, str]:
    """
    Parse DISCORD_MODERATION_CHANNELS au format:
       "avertissement:111111111111111111,kick:222222222222222222,
        bannissement:333333333333333333,rappel_a_lordre:444444444444444444"
       -> {111111111111111111: "avertissement", 222222222222222222: "kick", ...}
    """
    mapping: dict[int, str] = {}

    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue

        sanction_type, channel_id = pair.split(":", 1)
        sanction_type = sanction_type.strip()
        channel_id = channel_id.strip()

        if sanction_type not in VALID_SANCTION_TYPES:
            continue
        if not channel_id.isdigit():
            continue

        mapping[int(channel_id)] = sanction_type

    return mapping


# Exemple .env :
# DISCORD_MODERATION_CHANNELS=avertissement:ID_SALON_AVERT,
#   kick:ID_SALON_KICK,bannissement:ID_SALON_BAN,rappel_a_lordre:ID_SALON_RAPPEL
DISCORD_MODERATION_CHANNEL_TYPES = parse_moderation_channels(
    os.getenv("DISCORD_MODERATION_CHANNELS", "")
)
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
