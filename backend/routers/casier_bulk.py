"""Actions groupées sur les casiers (/api/moderation/casiers-bulk) : étiquette, suivi, export CSV.

Accès : rôle staff. Aucune action Discord. Les étiquettes (`tags`) et le suivi (`follow_up`) sont des
champs ajoutés au casier ; ils ne modifient ni les sanctions ni le statut calculé.
"""
import csv
import io
import logging
import os
import re
from datetime import date, datetime, timezone
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from database import db
from models.ticket import AuthenticatedHelper
from services import casier_service
from services.discord_service import DiscordService
from services.auth_service import current_staff, is_staff_helper
from services.notifications import create_notification

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/moderation/casiers-bulk", tags=["moderation-casiers-bulk"])

MAX_IDS = 100
MAX_TAG = 24
MAX_TAGS_PER_CASIER = 12
MAX_NOTE = 300
HEX_ID = re.compile(r"[0-9a-f]{24}")
DISCORD_ID = re.compile(r"[0-9]{17,20}")
CSV_COLUMNS = [
    "id", "discord_id", "pseudo", "statut", "sanctions", "rappels", "fiche_s_active",
    "derniere_sanction", "mute_jusqu_a", "etiquettes", "suivi_par", "suivi_echeance", "cree_le",
]


def _clean_ids(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if not isinstance(value, str) or not HEX_ID.fullmatch(value):
            raise ValueError("Identifiant de casier invalide.")
        if value not in seen:
            seen.append(value)
    return seen


class _Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    casier_ids: list[str] = Field(min_length=1, max_length=MAX_IDS)

    @field_validator("casier_ids")
    @classmethod
    def _ids(cls, value: list[str]) -> list[str]:
        return _clean_ids(value)


class TagIn(_Selection):
    tag: str = Field(min_length=1, max_length=MAX_TAG)


class FollowUpIn(_Selection):
    assignee_id: Optional[str] = None  # None = retirer le suivi
    note: str = Field(default="", max_length=MAX_NOTE)
    due_date: Optional[date] = None

    @field_validator("assignee_id")
    @classmethod
    def _assignee(cls, value):
        if value is not None and not DISCORD_ID.fullmatch(value):
            raise ValueError("Identifiant Discord invalide.")
        return value


def _oids(ids: list[str]) -> list[ObjectId]:
    return [ObjectId(value) for value in ids]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _author(staff: AuthenticatedHelper) -> dict:
    return casier_service.staff_to_author(staff)


async def _existing(ids: list[str], projection: dict | None = None) -> list[dict]:
    return [doc async for doc in db.casiers.find({"_id": {"$in": _oids(ids)}}, projection)]


@router.get("/meta")
async def bulk_meta(staff: AuthenticatedHelper = Depends(current_staff)):
    """Étiquettes et suivi de tous les casiers qui en portent."""
    items: dict[str, dict] = {}
    query = {"$or": [{"tags.0": {"$exists": True}}, {"follow_up": {"$type": "object"}}]}
    async for doc in db.casiers.find(query, {"tags": 1, "follow_up": 1}):
        items[str(doc["_id"])] = {"tags": list(doc.get("tags") or []), "follow_up": doc.get("follow_up")}
    return {"items": items}


@router.get("/assignees")
async def bulk_assignees(staff: AuthenticatedHelper = Depends(current_staff)):
    """Membres du staff pouvant recevoir un suivi."""
    role_id = os.getenv("DISCORD_STAFF_ROLE_ID")
    if not role_id:
        return {"items": [{"id": staff.id, "name": staff.global_name or staff.username}]}
    try:
        helpers = await DiscordService().fetch_helpers(role_id)
    except HTTPException:
        helpers = []
    items = [{"id": h.id, "name": h.display_name or h.username} for h in helpers]
    if not any(item["id"] == staff.id for item in items):
        items.insert(0, {"id": staff.id, "name": staff.global_name or staff.username})
    return {"items": sorted(items, key=lambda item: item["name"].casefold())}


@router.post("/tag")
async def bulk_tag(payload: TagIn, staff: AuthenticatedHelper = Depends(current_staff)):
    tag = payload.tag.strip()
    if not tag:
        raise HTTPException(status_code=422, detail="Étiquette vide.")
    updated = skipped = 0
    for doc in await _existing(payload.casier_ids, {"tags": 1}):
        tags = [t for t in (doc.get("tags") or []) if isinstance(t, str)]
        if tag.casefold() in {t.casefold() for t in tags}:
            skipped += 1
            continue
        if len(tags) >= MAX_TAGS_PER_CASIER:
            skipped += 1
            continue
        await db.casiers.update_one({"_id": doc["_id"]}, {"$set": {"tags": tags + [tag]}})
        updated += 1
    missing = len(payload.casier_ids) - updated - skipped
    return {"updated": updated, "skipped": skipped, "missing": missing}


@router.post("/untag")
async def bulk_untag(payload: TagIn, staff: AuthenticatedHelper = Depends(current_staff)):
    tag = payload.tag.strip().casefold()
    updated = 0
    for doc in await _existing(payload.casier_ids, {"tags": 1}):
        tags = [t for t in (doc.get("tags") or []) if isinstance(t, str)]
        kept = [t for t in tags if t.casefold() != tag]
        if len(kept) != len(tags):
            await db.casiers.update_one({"_id": doc["_id"]}, {"$set": {"tags": kept}})
            updated += 1
    return {"updated": updated, "skipped": len(payload.casier_ids) - updated, "missing": 0}


@router.post("/follow-up")
async def bulk_follow_up(payload: FollowUpIn, staff: AuthenticatedHelper = Depends(current_staff)):
    docs = await _existing(payload.casier_ids, {"discord_id": 1, "discord_member_snapshot": 1})
    if payload.assignee_id is None:
        for doc in docs:
            await db.casiers.update_one({"_id": doc["_id"]}, {"$unset": {"follow_up": ""}})
        return {"updated": len(docs), "skipped": 0, "missing": len(payload.casier_ids) - len(docs)}

    if not await is_staff_helper(payload.assignee_id):
        raise HTTPException(status_code=422, detail="La personne désignée n'est pas membre du staff.")
    assignee_name = payload.assignee_id
    if payload.assignee_id == staff.id:
        assignee_name = staff.global_name or staff.username
    else:
        try:
            member = await DiscordService()._get(f"/guilds/{os.getenv('DISCORD_GUILD_ID')}/members/{payload.assignee_id}")
            user = member.get("user") or {}
            assignee_name = member.get("nick") or user.get("global_name") or user.get("username") or assignee_name
        except Exception:  # noqa: BLE001 - le nom est facultatif
            pass
    follow_up = {
        "assignee_id": payload.assignee_id,
        "assignee_name": assignee_name,
        "note": payload.note.strip(),
        "due_date": payload.due_date.isoformat() if payload.due_date else None,
        "assigned_by": _author(staff),
        "assigned_at": _now(),
    }
    for doc in docs:
        await db.casiers.update_one({"_id": doc["_id"]}, {"$set": {"follow_up": follow_up}})
    if docs and payload.assignee_id != staff.id:
        await create_notification(
            payload.assignee_id,
            "casier_follow_up",
            "Suivi de casier assigné",
            f"{len(docs)} casier(s) à suivre." + (f" Échéance {follow_up['due_date']}." if follow_up["due_date"] else ""),
            "/moderation/casiers",
        )
    return {"updated": len(docs), "skipped": 0, "missing": len(payload.casier_ids) - len(docs)}


def _csv_cell(value) -> str:
    """Neutralise l'injection de formule (=, +, -, @, tab, retour chariot) à l'ouverture dans un tableur."""
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


@router.post("/export")
async def bulk_export(payload: _Selection, staff: AuthenticatedHelper = Depends(current_staff)):
    now = datetime.now(timezone.utc)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    docs = await _existing(payload.casier_ids, {"fiches_s.content": 0, "fiches_s.revisions": 0})
    for doc in sorted(docs, key=lambda d: payload.casier_ids.index(str(d["_id"]))):
        summary = casier_service.summarize(doc, now)
        snapshot = doc.get("discord_member_snapshot") or {}
        follow = doc.get("follow_up") or {}
        writer.writerow([
            _csv_cell(v) for v in (
                str(doc["_id"]), doc.get("discord_id"),
                snapshot.get("display_name") or snapshot.get("username"),
                summary["status"], summary["sanctions_count"], summary["rappels_count"],
                "oui" if summary["has_active_fiche_s"] else "non",
                summary["last_sanction_at"], summary["active_mute_until"],
                " | ".join(doc.get("tags") or []),
                follow.get("assignee_name"), follow.get("due_date"), doc.get("created_at"),
            )
        ])
    stamp = now.strftime("%Y%m%d-%H%M")
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="casiers-{stamp}.csv"', "Cache-Control": "no-store"},
    )
