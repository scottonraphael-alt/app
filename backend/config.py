import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")


def _int_env(name: str, default: int, minimum: int | None = None) -> int:
    """Entier lu dans l'environnement ; valeur illisible (ou sous `minimum`) → `default`."""
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    if minimum is not None and value < minimum:
        return default
    return value


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_origins(raw: str) -> list[str]:
    origins = [o.strip().rstrip("/") for o in raw.split(",") if o.strip() and o.strip() != "*"]
    return origins or ["https://iris.loasis.app"]


def _parse_ids(raw: str) -> set[str]:
    return {item.strip() for item in raw.split(",") if item.strip().isdigit()}


MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
# "*" est ignoré : incompatible avec allow_credentials=True. Défaut = le front de prod.
CORS_ORIGINS = _parse_origins(os.environ.get("CORS_ORIGINS", ""))
DISCORD_GUILD_ID = os.environ.get("DISCORD_GUILD_ID")
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI")
APP_SESSION_SECRET = os.environ.get("APP_SESSION_SECRET")
DISCORD_HELPER_ROLE_ID = os.environ.get("DISCORD_HELPER_ROLE_ID")
DISCORD_ADMIN_ROLE_ID = os.environ.get("DISCORD_ADMIN_ROLE_ID")
DISCORD_TICKET_CATEGORY_ID = os.environ.get("DISCORD_TICKET_CATEGORY_ID")
# Catégories de tickets supplémentaires, séparées par des virgules (ex. catégorie où le bot
# range les tickets fermés, ou salon qui héberge les fils de tickets). DISCORD_TICKET_CATEGORY_ID
# reste toujours autorisée. Chaque refus est journalisé avec la catégorie du salon.
DISCORD_TICKET_CATEGORY_IDS = _parse_ids(os.environ.get("DISCORD_TICKET_CATEGORY_IDS", ""))
ALLOWED_TICKET_CATEGORY_IDS = frozenset(
    DISCORD_TICKET_CATEGORY_IDS | ({DISCORD_TICKET_CATEGORY_ID} if DISCORD_TICKET_CATEGORY_ID else set())
)
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY")
DISCORD_STAFF_ROLE_ID = os.environ.get("DISCORD_STAFF_ROLE_ID")
DISCORD_RESPONSABLE_ROLE_ID = os.environ.get("DISCORD_RESPONSABLE_ROLE_ID")
DISCORD_HELPER_ROLE2_ID = os.environ.get("DISCORD_HELPER_ROLE2_ID")
DISCORD_ANIMATEUR_ROLE_ID = os.getenv("DISCORD_ANIMATEUR_ROLE_ID", "")
DISCORD_OPERATEUR_ROLE_ID = os.getenv("DISCORD_OPERATEUR_ROLE_ID", "")
DISCORD_OPERATEUR_ROLE2_ID = os.getenv("DISCORD_OPERATEUR_ROLE2_ID", "")
# Rôle « Adjoint » : purement esthétique (badge du tableau de bord), ne donne aucun accès.
DISCORD_ADJOINT_ROLE_ID = os.getenv("DISCORD_ADJOINT_ROLE_ID", "1502192430387040407")

# --- Sécurité / logs d'auth ---
TRUSTED_PROXIES = os.environ.get(
    "TRUSTED_PROXIES",
    "127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,::1/128,fc00::/7",
)
AUTH_LOG_TTL_DAYS = _int_env("AUTH_LOG_TTL_DAYS", 180)
AUTH_SESSION_RATE_LIMIT = _int_env("AUTH_SESSION_RATE_LIMIT", 120)
AUTH_SESSION_RATE_WINDOW = _int_env("AUTH_SESSION_RATE_WINDOW", 60)
AUTH_INVALID_LOG_INTERVAL = _int_env("AUTH_INVALID_LOG_INTERVAL", 300)


def missing_discord_bot_settings() -> list[str]:
    required = {
        "DISCORD_GUILD_ID": DISCORD_GUILD_ID,
        "DISCORD_BOT_TOKEN": DISCORD_BOT_TOKEN,
        "DISCORD_HELPER_ROLE_ID": DISCORD_HELPER_ROLE_ID,
        "DISCORD_ADMIN_ROLE_ID": DISCORD_ADMIN_ROLE_ID,
        "DISCORD_TICKET_CATEGORY_ID": DISCORD_TICKET_CATEGORY_ID,
    }
    return [name for name, value in required.items() if not value]


VALID_SANCTION_TYPES = {"avertissement", "mute", "bannissement", "kick", "rappel_a_lordre"}


def parse_moderation_channels(raw: str) -> dict[int, str]:
    """
    Parse DISCORD_MODERATION_CHANNELS au format:
       "avertissement:111111111111111111,mute:555555555555555555,kick:222222222222222222,
        bannissement:333333333333333333,rappel_a_lordre:444444444444444444"
       -> {111111111111111111: "avertissement", 555555555555555555: "mute", ...}
    Les entrées au type inconnu ou à l'identifiant non numérique sont ignorées.
    """
    mapping: dict[int, str] = {}

    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue

        sanction_type, channel_id = pair.split(":", 1)
        sanction_type = sanction_type.strip().lower()
        channel_id = channel_id.strip()

        if sanction_type not in VALID_SANCTION_TYPES:
            continue
        if not channel_id.isdigit():
            continue

        mapping[int(channel_id)] = sanction_type

    return mapping


# Exemple .env :
# DISCORD_MODERATION_CHANNELS=avertissement:ID_SALON_AVERT,mute:ID_SALON_MUTE,
#   kick:ID_SALON_KICK,bannissement:ID_SALON_BAN,rappel_a_lordre:ID_SALON_RAPPEL
DISCORD_MODERATION_CHANNEL_TYPES = parse_moderation_channels(
    os.getenv("DISCORD_MODERATION_CHANNELS", "")
)

# Rôles temporaires du parcours privé /sanction (retirés après l'action).
SANCTION_TEMP_ROLE_ID = os.getenv("SANCTION_TEMP_ROLE_ID", "1550298577098514482")
SANCTION_PERMANENT_BAN_ROLE_ID = os.getenv("SANCTION_PERMANENT_BAN_ROLE_ID", "1550298773635211305")
SANCTION_PERMANENT_BAN_ADMIN_ROLE_ID = os.getenv("SANCTION_PERMANENT_BAN_ADMIN_ROLE_ID", "1321630097744199721")

# --- Casier : fichiers des sanctions ---
# Plafond par fichier copié depuis un log Discord (25 Mo par défaut).
CASIER_ATTACHMENT_MAX_BYTES = _int_env("CASIER_ATTACHMENT_MAX_BYTES", 25 * 1024 * 1024, minimum=1)
# Plafond par fichier ajouté à la main sur une sanction (10 Mo par défaut).
CASIER_UPLOAD_MAX_BYTES = _int_env("CASIER_UPLOAD_MAX_BYTES", 10 * 1024 * 1024, minimum=1)

# --- Signalements de la modération IA (collection ai_moderation_flags) ---
# Rétention (index TTL sur created_at) : 180 jours par défaut, 0 = conservation illimitée.
AI_MODERATION_FLAG_TTL_DAYS = _int_env("AI_MODERATION_FLAG_TTL_DAYS", 180, minimum=0)
# Salons/catégories d'écoute dont les signalements ne sont jamais enregistrés dans Iris,
# en plus des catégories de tickets (ALLOWED_TICKET_CATEGORY_IDS). L'alerte Discord n'est pas affectée.
AI_MODERATION_FLAG_SKIP_IDS = frozenset(_parse_ids(os.environ.get("AI_MODERATION_FLAG_SKIP_IDS", "")))
# Texte des messages que le modèle a refusé d'analyser (souvent des messages de détresse) :
# non conservé par défaut, seuls l'auteur, le salon, la date et le lien sont gardés.
AI_MODERATION_FLAG_STORE_REFUSAL_CONTENT = _bool_env("AI_MODERATION_FLAG_STORE_REFUSAL_CONTENT", False)


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

# Synthèses des tickets (clé exclusivement côté serveur).
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
TICKET_SUMMARY_MODEL = os.getenv("TICKET_SUMMARY_MODEL", "claude-haiku-5-5").strip()

# Rappels de suivi Discord (dimanche midi, Europe/Paris).
TICKET_REMINDER_CHANNEL_ID = "1499495750151966862"
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://iris.loasis.app").rstrip("/")

# Récapitulatif quotidien des tâches d’animation (10 h, Europe/Paris).
PROJECT_REMINDER_CHANNEL_ID = "1534270215490244829"
