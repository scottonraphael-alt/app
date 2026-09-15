from datetime import datetime, timezone

from bson import ObjectId

from database import db

SANCTION_TYPES = {"avertissement", "bannissement", "kick", "rappel_a_lordre"}

STATUS_SEVERITY = {
    "vierge": 0,
    "vigilance": 1,
    "surveillance": 2,
    "sanctionne": 3,
    "bloque": 4,
}

BOT_AUTHOR = {
    "id": None,
    "username": "bot",
    "display_name": "Bot Modération",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def has_active_fiche_s(casier: dict) -> bool:
    return any(fiche.get("active") for fiche in casier.get("fiches_s", []))


def compute_status(casier: dict) -> str:
    sanctions = casier.get("sanctions", [])

    has_ban = any(s.get("type") == "bannissement" for s in sanctions)
    has_kick = any(s.get("type") == "kick" for s in sanctions)
    has_warning = any(s.get("type") == "avertissement" for s in sanctions)
    has_reminder = any(s.get("type") == "rappel_a_lordre" for s in sanctions)

    if has_ban:
        base_status = "bloque"
    elif has_kick:
        base_status = "sanctionne"
    elif has_warning:
        base_status = "surveillance"
    elif has_reminder:
        base_status = "vigilance"
    else:
        base_status = "vierge"

    if has_active_fiche_s(casier):
        minimum_status = "surveillance"
        if STATUS_SEVERITY[base_status] < STATUS_SEVERITY[minimum_status]:
            return minimum_status

    return base_status


def staff_to_author(staff) -> dict:
    return {
        "id": getattr(staff, "id", None),
        "username": getattr(staff, "username", None),
        "display_name": getattr(staff, "display_name", None),
    }


async def get_or_create_casier(discord_id: str, snapshot: dict, created_by: dict | None = None) -> dict:
    """Retourne le casier existant, ou en crée un si aucun n'existe pour ce discord_id."""
    casier = await db.casiers.find_one({"discord_id": discord_id})
    if casier:
        if snapshot and snapshot.get("username"):
            await db.casiers.update_one(
                {"_id": casier["_id"]},
                {"$set": {"discord_member_snapshot": snapshot}},
            )
            casier["discord_member_snapshot"] = snapshot
        return casier

    now = now_iso()
    document = {
        "discord_id": discord_id,
        "created_at": now,
        "status": "vierge",
        "discord_member_snapshot": snapshot,
        "created_by": created_by or BOT_AUTHOR,
        "sanctions": [],
        "fiches_s": [],
    }

    result = await db.casiers.insert_one(document)
    document["_id"] = result.inserted_id
    return document


async def add_sanction(
    discord_id: str,
    sanction_type: str,
    reason: str,
    snapshot: dict,
    created_by: dict | None = None,
    duration: str | None = None,
    source: dict | None = None,
    dedupe_message_id: str | None = None,
) -> dict:
    """Ajoute une sanction, en créant le casier au besoin.

    Si `dedupe_message_id` correspond à une sanction déjà enregistrée avec le
    même message source, l'insertion est ignorée (protège contre les doublons
    si le bot retraite un message, ex. après reconnexion).
    """
    if sanction_type not in SANCTION_TYPES:
        raise ValueError(f"Type de sanction invalide : {sanction_type}")

    casier = await get_or_create_casier(discord_id, snapshot, created_by)

    if dedupe_message_id:
        already_logged = any(
            (s.get("source") or {}).get("message_id") == dedupe_message_id
            for s in casier.get("sanctions", [])
        )
        if already_logged:
            return casier

    sanction = {
        "type": sanction_type,
        "reason": reason.strip()[:1000] if reason else "",
        "created_at": now_iso(),
        "created_by": created_by or BOT_AUTHOR,
        "duration": duration,
        "source": source,
    }

    await db.casiers.update_one({"_id": casier["_id"]}, {"$push": {"sanctions": sanction}})

    updated = await db.casiers.find_one({"_id": casier["_id"]})
    return updated


async def add_fiche_s(
    discord_id: str,
    title: str,
    content: str,
    snapshot: dict,
    created_by: dict | None = None,
) -> dict:
    casier = await get_or_create_casier(discord_id, snapshot, created_by)

    fiche = {
        "id": str(ObjectId()),
        "title": title.strip(),
        "content": content,
        "created_at": now_iso(),
        "created_by": created_by or BOT_AUTHOR,
        "active": True,
        "closed_at": None,
        "closed_by": None,
    }

    await db.casiers.update_one({"_id": casier["_id"]}, {"$push": {"fiches_s": fiche}})

    updated = await db.casiers.find_one({"_id": casier["_id"]})
    return updated

async def get_casier_by_discord_id(discord_id: str) -> dict | None:
    """Retourne le casier d'un membre, ou None s'il n'existe pas encore."""
    return await db.casiers.find_one({"discord_id": discord_id})
    
async def close_fiche_s(casier_id: ObjectId, fiche_id: str, closed_by: dict) -> dict | None:
    casier = await db.casiers.find_one({"_id": casier_id})
    if not casier:
        return None

    target = next((f for f in casier.get("fiches_s", []) if f.get("id") == fiche_id), None)
    if not target or not target.get("active", True):
        return None

    await db.casiers.update_one(
        {"_id": casier_id, "fiches_s.id": fiche_id},
        {
            "$set": {
                "fiches_s.$.active": False,
                "fiches_s.$.closed_at": now_iso(),
                "fiches_s.$.closed_by": closed_by,
            }
        },
    )

    return await db.casiers.find_one({"_id": casier_id})
