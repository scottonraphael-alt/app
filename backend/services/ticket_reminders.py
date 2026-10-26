"""Rappels V2 du dimanche à midi (Europe/Paris), sans contenu des conversations."""
import asyncio
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

import config
from database import db
from services.discord_service import DiscordService, DISCORD_API_BASE
from services.ticket_assignment import ticket_helper_role_ids

logger = logging.getLogger(__name__)
PARIS = ZoneInfo("Europe/Paris")
INACTIVITY = timedelta(days=7)


def parse_date(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def last_human_update(ticket):
    explicit = parse_date(ticket.get("last_helper_update_at"))
    if explicit:
        return explicit
    # Repli pour les anciens dossiers : updated_at est volontairement ignoré,
    # car les synchronisations automatiques le modifient elles aussi.
    dates = [parse_date(ticket.get("created_at"))]
    synced = parse_date(ticket.get("last_synced_at"))
    updated = parse_date(ticket.get("updated_at"))
    if synced and updated and updated > synced:
        # Une intervention humaine est encore identifiable si elle est postérieure
        # à la dernière synchronisation (repli réservé aux dossiers anciens).
        dates.append(updated)
    dates.extend(parse_date(note.get("updated_at")) for note in ticket.get("notes_entries", []))
    summary = ticket.get("ai_summary") or {}
    if summary.get("generated_by") and not summary["generated_by"].startswith("system:"):
        dates.append(parse_date(summary.get("generated_at")))
    return max((date for date in dates if date), default=None)


def sunday_slot(now):
    local = now.astimezone(PARIS)
    if local.weekday() != 6 or local.hour < 12:
        return None
    return f"weekly:{local.date().isoformat()}"


async def stale_tickets(now):
    discord = DiscordService()
    helpers = {person.id for person in await discord.fetch_helpers(ticket_helper_role_ids())}
    candidates = db.tickets.find(
        {"status": "active", "demo_ticket": {"$ne": True}},
        {"_id": 0, "id": 1, "assigned_helper.id": 1, "created_at": 1,
         "last_helper_update_at": 1, "last_synced_at": 1, "updated_at": 1, "notes_entries.updated_at": 1,
         "ai_summary.generated_at": 1, "ai_summary.generated_by": 1},
    )
    result = []
    async for ticket in candidates:
        helper_id = (ticket.get("assigned_helper") or {}).get("id", "")
        if helper_id not in helpers or not re.fullmatch(r"[0-9]{15,22}", helper_id):
            continue
        updated = last_human_update(ticket)
        if updated and now - updated >= INACTIVITY:
            result.append({"id": ticket["id"], "helper_id": helper_id, "updated": updated})
    return sorted(result, key=lambda row: (row["helper_id"], row["updated"], row["id"]))


def message_payloads(rows, *, test=False):
    site = config.FRONTEND_URL
    parsed = urlsplit(site)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
        raise HTTPException(503, "FRONTEND_URL doit contenir l’adresse publique d’Iris.")
    pages = [rows[index:index + 8] for index in range(0, len(rows), 8)]
    if not pages:
        pages = [[]] if test else []
    mentioned = set()
    payloads = []
    for page_number, page in enumerate(pages, 1):
        title = "🌿 Suivi des dossiers d’écoute"
        if test:
            title = "🧪 Test du rappel de suivi"
        if len(pages) > 1:
            title += f" · {page_number}/{len(pages)}"
        components = [
            {"type": 10, "content": f"## {title}\nCes dossiers ouverts n’ont pas été mis à jour manuellement depuis au moins 7 jours. Merci de faire le point sur leur suivi." if rows else f"## {title}\nL’envoi Discord V2 fonctionne. Aucun dossier ouvert attribué à un Helper ou Helper+ n’est en retard actuellement."},
        ]
        users = []
        for index, row in enumerate(page, (page_number - 1) * 8 + 1):
            helper_id = row["helper_id"]
            if helper_id not in mentioned:
                users.append(helper_id)
                mentioned.add(helper_id)
            date = row["updated"].astimezone(PARIS).strftime("%d/%m/%Y à %H:%M")
            components.append(
                {"type": 9, "components": [{"type": 10, "content": f"<@{helper_id}> · **Dossier {index}**\nDernière mise à jour : {date}"}],
                 "accessory": {"type": 2, "style": 5, "label": "Ouvrir le dossier", "url": f"{site}/tickets/{quote(str(row['id']), safe='')}"}},
            )
        components.append({"type": 10, "content": "-# Iris · Rappel chaque dimanche à 12 h (heure de Paris). Les actualisations automatiques ne comptent pas comme un suivi manuel."})
        payloads.append({
            "flags": 32768,
            "components": [{"type": 17, "accent_color": 0x486B5B, "components": components}],
            "allowed_mentions": {"parse": [], "users": users, "roles": [], "replied_user": False},
        })
    return payloads


async def post_discord_message(payload):
    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(3):
            try:
                response = await client.post(
                    f"{DISCORD_API_BASE}/channels/{config.TICKET_REMINDER_CHANNEL_ID}/messages",
                    headers={"Authorization": f"Bot {config.DISCORD_BOT_TOKEN}"}, json=payload,
                )
            except httpx.RequestError as error:
                raise HTTPException(503, "Discord n’a pas confirmé l’envoi. Vérifiez le salon avant de refaire un test.") from error
            if response.status_code == 429 and attempt < 2:
                await asyncio.sleep(min(float(response.json().get("retry_after", 1)), 60))
                continue
            if response.is_error:
                logger.warning("Rappel Discord refusé (HTTP %s).", response.status_code)
                raise HTTPException(502, "Discord a refusé l’envoi. Vérifiez les droits du bot dans le salon de rappel.")
            return response.json()
    raise HTTPException(503, "Discord est temporairement indisponible.")


async def send_reminder(now, *, test=False, run_id=None):
    # Vérification de la guilde via l’API existante, avant tout envoi dans le salon fixé.
    await DiscordService().fetch_text_channel(config.TICKET_REMINDER_CHANNEL_ID)
    rows = await stale_tickets(now)
    urls = []
    for index, payload in enumerate(message_payloads(rows, test=test)):
        payload["nonce"] = hashlib.sha256(f"{run_id}:{index}".encode()).hexdigest()[:25]
        payload["enforce_nonce"] = True
        sent = await post_discord_message(payload)
        message_id = str(sent["id"])
        urls.append(f"https://discord.com/channels/{config.DISCORD_GUILD_ID}/{config.TICKET_REMINDER_CHANNEL_ID}/{message_id}")
        if run_id:
            await db.ticket_reminder_runs.update_one({"_id": run_id}, {"$push": {"message_ids": message_id}})
    return {"ticket_count": len(rows), "helper_count": len({row["helper_id"] for row in rows}), "message_urls": urls}


async def test_reminder():
    now = datetime.now(timezone.utc)
    # Limite globale : deux coordinateurs ne peuvent pas déclencher un test en parallèle.
    await db.ticket_reminder_controls.update_one({"_id": "test"}, {"$setOnInsert": {"next_at": now.isoformat()}}, upsert=True)
    claim = await db.ticket_reminder_controls.find_one_and_update(
        {"_id": "test", "next_at": {"$lte": now.isoformat()},
         "$or": [{"running": {"$ne": True}}, {"running_until": {"$lte": now.isoformat()}}]},
        {"$set": {"next_at": (now + timedelta(seconds=60)).isoformat(), "running": True, "running_until": (now + timedelta(minutes=10)).isoformat()}},
    )
    if not claim:
        raise HTTPException(429, "Un test est déjà en cours ou vient d’être envoyé. Patientez une minute.")
    run_id = f"test:{uuid4()}"
    await db.ticket_reminder_runs.insert_one({"_id": run_id, "kind": "test", "status": "sending", "created_at": now.isoformat()})
    try:
        result = await send_reminder(now, test=True, run_id=run_id)
        await db.ticket_reminder_runs.update_one({"_id": run_id}, {"$set": {"status": "sent", "result": result}})
        return result
    except Exception:
        await db.ticket_reminder_runs.update_one({"_id": run_id}, {"$set": {"status": "failed"}})
        raise
    finally:
        await db.ticket_reminder_controls.update_one({"_id": "test"}, {"$set": {"running": False}})


async def scheduled_reminder(now=None):
    now = now or datetime.now(timezone.utc)
    slot = sunday_slot(now)
    if not slot:
        return
    try:
        await db.ticket_reminder_runs.insert_one({"_id": slot, "kind": "weekly", "status": "sending", "created_at": now.isoformat()})
    except DuplicateKeyError:
        return  # Déjà traité, même après redémarrage ou sur plusieurs workers API.
    try:
        result = await send_reminder(now, run_id=slot)
        await db.ticket_reminder_runs.update_one({"_id": slot}, {"$set": {"status": "sent" if result["message_urls"] else "empty", "result": result}})
    except Exception:
        # Une réponse réseau incertaine ne doit pas provoquer plusieurs pings. Le statut
        # persiste pour diagnostic, et le bouton permet de vérifier l’envoi manuellement.
        await db.ticket_reminder_runs.update_one({"_id": slot}, {"$set": {"status": "failed"}})
        logger.exception("Le rappel hebdomadaire des dossiers a échoué (%s).", slot)


async def run_ticket_reminders():
    while True:
        try:
            await scheduled_reminder()
        except Exception:
            logger.exception("Impossible d’exécuter le planificateur des rappels de suivi.")
        await asyncio.sleep(30)
