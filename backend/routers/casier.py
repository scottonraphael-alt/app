"""Casiers de modération : liste et super recherche, détail, sanctions, informations complémentaires,
fichiers, fiches S, signalements IA et route Ghost Bot.

Routes de modification : validation → écriture → journal `casier.*` (`casier_audit.log_casier_event`,
qui n'échoue jamais) → réponse construite depuis le snapshot, sans appel Discord. Seul
`GET /{casier_id}` rafraîchit le membre, au plus une fois toutes les 10 minutes par casier.
"""
import hmac
import logging
import os
import re
from datetime import datetime, timezone

import httpx
from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.security.api_key import APIKeyHeader

from database import db
from models.casier import (
    ATTACHMENT_ID_PATTERN,
    HEX_ID_PATTERN,
    AiFlagKind,
    AiFlagListResponse,
    AiFlagOut,
    AiFlagReviewFilter,
    BotCasierResponse,
    CasierDetailResponse,
    CasierListItem,
    CasierMember,
    CasierResponse,
    CasierSort,
    CreateCasierPayload,
    CreateFicheSPayload,
    CreateSanctionPayload,
    MemberSearchResult,
    NotePayload,
    ReviewAiFlagPayload,
    SearchScope,
    UpdateFicheSPayload,
)
from services import (
    casier_ai_flags,
    casier_attachments,
    casier_audit,
    casier_history,
    casier_log_parser,
    casier_migrations,
    casier_search,
    casier_service,
)
from services.auth_service import current_staff, get_helper_role_flags

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/moderation/casiers", tags=["moderation-casiers"])

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")
DISCORD_API_BASE = "https://discord.com/api/v10"

GHOST_BOT_API_KEY = os.getenv("GHOST_BOT_API_KEY")
GHOST_BOT_STATUS_FORMATS = ("legacy", "v2")
# Valeurs de statut renvoyées à Ghost Bot (anciennes par défaut) ; `?status_format=` reste prioritaire.
GHOST_BOT_STATUS_FORMAT = (os.getenv("GHOST_BOT_STATUS_FORMAT") or "legacy").strip().lower()
if GHOST_BOT_STATUS_FORMAT not in GHOST_BOT_STATUS_FORMATS:
    logger.warning(
        "GHOST_BOT_STATUS_FORMAT=%r inconnu (legacy ou v2) : format legacy utilisé.", GHOST_BOT_STATUS_FORMAT
    )
    GHOST_BOT_STATUS_FORMAT = "legacy"

# Au plus un appel Discord par casier sur cette durée, même si le détail est sondé toutes les 4 s.
CASIER_MEMBER_REFRESH_SECONDS = 600

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Snowflake Discord : uniquement des chiffres ASCII (aucun autre caractère ne doit atteindre une URL Discord).
DISCORD_ID_PATTERN = re.compile(r"[0-9]{17,20}")

SANCTION_LABELS = {
    "avertissement": "⚠️ Avertissement",
    "mute": "🔇 Mute",
    "kick": "👢 Kick",
    "bannissement": "🔨 Bannissement",
    "rappel_a_lordre": "📢 Rappel à l'ordre",
}

# La liste ne charge ni le contenu des fiches S ni leurs versions précédentes.
LIST_PROJECTION = {"fiches_s.content": 0, "fiches_s.revisions": 0}


# --- Identifiants -----------------------------------------------------------------------------


def object_id_or_400(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception:
        raise HTTPException(status_code=400, detail="Identifiant invalide.")


def hex_id_or_400(value) -> str:
    if not isinstance(value, str) or not HEX_ID_PATTERN.fullmatch(value):
        raise HTTPException(status_code=400, detail="Identifiant invalide.")
    return value


def attachment_id_or_400(value) -> str:
    if not isinstance(value, str) or not ATTACHMENT_ID_PATTERN.fullmatch(value):
        raise HTTPException(status_code=400, detail="Identifiant invalide.")
    return value


def is_discord_id(value) -> bool:
    return isinstance(value, str) and DISCORD_ID_PATTERN.fullmatch(value) is not None


def discord_id_or_422(value: str | None) -> str:
    cleaned = (value or "").strip()
    if not is_discord_id(cleaned):
        raise HTTPException(status_code=422, detail="Identifiant Discord invalide.")
    return cleaned


# --- Discord ----------------------------------------------------------------------------------


def ensure_discord_config():
    if not DISCORD_BOT_TOKEN or not DISCORD_GUILD_ID:
        raise HTTPException(status_code=500, detail="Configuration Discord manquante.")


def discord_headers() -> dict:
    ensure_discord_config()
    return {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}


def discord_avatar_url(user: dict) -> str | None:
    avatar = user.get("avatar")
    user_id = user.get("id")
    if not avatar or not user_id:
        return None
    return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png"


async def verify_bot_api_key(api_key: str | None = Depends(api_key_header)) -> str:
    if (
        not GHOST_BOT_API_KEY
        or not api_key
        or not hmac.compare_digest(api_key.encode("utf-8"), GHOST_BOT_API_KEY.encode("utf-8"))
    ):
        raise HTTPException(status_code=401, detail="Clé API invalide ou manquante.")
    return api_key


async def search_guild_members(query: str, limit: int = 10) -> list[dict]:
    url = f"{DISCORD_API_BASE}/guilds/{DISCORD_GUILD_ID}/members/search"
    params = {"query": query, "limit": max(1, min(limit, 25))}

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, headers=discord_headers(), params=params)

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Recherche Discord impossible ({response.status_code}).",
        )

    payload = response.json()
    results = []

    for item in payload:
        user = item.get("user", {})
        results.append(
            {
                "id": user.get("id"),
                "username": user.get("username") or user.get("id"),
                "display_name": item.get("nick") or user.get("global_name") or user.get("username"),
                "avatar_url": discord_avatar_url(user),
            }
        )

    return results


async def fetch_guild_member(discord_id: str) -> dict | None:
    if not is_discord_id(discord_id):
        return None

    url = f"{DISCORD_API_BASE}/guilds/{DISCORD_GUILD_ID}/members/{discord_id}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, headers=discord_headers())

    if response.status_code == 404:
        return None

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Impossible de récupérer le membre Discord ({response.status_code}).",
        )

    return response.json()


def snapshot_from_guild_member(guild_member: dict) -> dict:
    user = guild_member.get("user", {})
    return {
        "id": user.get("id"),
        "username": user.get("username") or user.get("id"),
        "display_name": guild_member.get("nick")
        or user.get("global_name")
        or user.get("username"),
        "avatar_url": discord_avatar_url(user),
    }


def _text_or_none(value) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def member_from_snapshot(snapshot: dict | None, discord_id: str | None = None) -> CasierMember:
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    fallback = str(discord_id or "") or "inconnu"
    member_id = _text_or_none(snapshot.get("id")) or fallback
    username = _text_or_none(snapshot.get("username")) or _text_or_none(snapshot.get("display_name")) or fallback
    return CasierMember(
        id=member_id,
        username=username,
        display_name=_text_or_none(snapshot.get("display_name")) or (None if snapshot else fallback),
        avatar_url=_text_or_none(snapshot.get("avatar_url")),
    )


async def resolve_member(
    discord_id: str, snapshot: dict | None, *, casier_oid: ObjectId | None = None
) -> tuple[CasierMember, bool | None]:
    """Rafraîchit le membre depuis Discord, sans jamais échouer (repli sur le snapshot).

    Renvoie (membre, is_prevention) ; `None` = valeur stockée conservée (membre absent ou Discord
    indisponible). `member_refreshed_at` est écrit à chaque tentative.
    """
    try:
        guild_member = await fetch_guild_member(discord_id)
    except Exception:
        logger.warning("Rafraîchissement Discord impossible pour %s.", discord_id, exc_info=True)
        guild_member = None

    fresh_snapshot = None
    if isinstance(guild_member, dict):
        candidate = snapshot_from_guild_member(guild_member)
        if candidate.get("id") and candidate.get("username"):
            fresh_snapshot = {key: _text_or_none(value) for key, value in candidate.items()}

    update: dict = {"member_refreshed_at": casier_service.now_iso()}
    if fresh_snapshot:
        if fresh_snapshot != snapshot:
            update["discord_member_snapshot"] = fresh_snapshot
        update["is_prevention"] = False
    target = {"_id": casier_oid} if casier_oid is not None else {"discord_id": discord_id}
    try:
        await db.casiers.update_one(target, {"$set": update})
    except Exception:
        logger.warning("Rafraîchissement du membre %s non enregistré.", discord_id, exc_info=True)

    if fresh_snapshot:
        return CasierMember(**fresh_snapshot), False
    return member_from_snapshot(snapshot, discord_id), None


async def resolve_log_author(mod_id: str) -> dict:
    """Modérateur cité dans un log OasisBot (resync) : nom via Discord en best-effort, sinon l'id seul."""
    try:
        guild_member = await fetch_guild_member(mod_id)
    except Exception:
        logger.warning("Nom du modérateur %s introuvable sur Discord.", mod_id, exc_info=True)
        guild_member = None
    if isinstance(guild_member, dict):
        user = guild_member.get("user") or {}
        return {
            "id": str(mod_id),
            "username": _text_or_none(user.get("username")),
            "display_name": _text_or_none(
                guild_member.get("nick") or user.get("global_name") or user.get("username")
            ),
        }
    return {"id": str(mod_id), "username": None, "display_name": None}


# --- Markdown Ghost Bot -----------------------------------------------------------------------


def format_date(iso_date: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_date)
        return dt.strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return iso_date or "date inconnue"


def sanctions_to_markdown(casier: dict) -> str:
    sanctions = sorted(
        casier.get("sanctions", []),
        key=lambda s: s.get("created_at", ""),
        reverse=True,
    )

    if not sanctions:
        return "*Aucune sanction enregistrée.*"

    lines = []
    for s in sanctions:
        label = SANCTION_LABELS.get(s.get("type"), s.get("type", "Sanction"))
        date = format_date(s.get("created_at", ""))
        reason = s.get("reason") or "Aucune raison renseignée."
        duration = f" ({s['duration']})" if s.get("duration") else ""

        lines.append(f"**{label}**{duration} — {date}\n> {reason}")

    return "\n\n".join(lines)


# --- Construction des réponses ----------------------------------------------------------------


def _items(container, key: str) -> list[dict]:
    value = container.get(key) if isinstance(container, dict) else None
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _parse_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and value.strip():
        try:
            moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _author_out(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    return {key: _text_or_none(value.get(key)) for key in ("id", "username", "display_name")}


def _int_or_none(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


async def viewer_for(staff) -> dict:
    """Lecteur courant pour `can_edit`/`can_delete` (rôles en cache 60 s, déjà lus par `current_staff`)."""
    flags = await get_helper_role_flags(staff.id)
    return {"id": staff.id, "is_responsable": bool(flags.get("is_responsable"))}


def sanction_out(sanction: dict, casier_id: str, viewer: dict, now: datetime) -> dict:
    sanction_id = str(sanction.get("id") or "")
    source = sanction.get("source") if isinstance(sanction.get("source"), dict) else None
    notes = [casier_service.note_to_out(note, viewer) for note in casier_service.visible_notes(sanction)]
    notes.sort(key=lambda note: casier_search.timestamp_of(note["created_at"]))
    return {
        "id": sanction_id,
        "type": str(sanction.get("type") or "sanction"),
        "reason": str(sanction.get("reason") or ""),
        "created_at": sanction.get("created_at") or "",
        "created_by": _author_out(sanction.get("created_by")),
        "moderator": _author_out(sanction.get("moderator")),
        "duration": _text_or_none(sanction.get("duration")),
        "duration_seconds": _int_or_none(sanction.get("duration_seconds")),
        "expires_at": sanction.get("expires_at"),
        "is_active": casier_service.is_sanction_active(sanction, now),
        "origin": casier_service.sanction_origin(sanction),
        "source": {key: _text_or_none(source.get(key)) for key in ("channel_id", "message_id", "message_url")}
        if source
        else None,
        "attachments": casier_attachments.attachments_out(sanction, casier_id, viewer),
        "notes": notes,
        "ai_flag_id": _text_or_none(sanction.get("ai_flag_id")),
    }


def summary_fields(summary: dict) -> dict:
    """Champs de `casier_service.summarize` communs à la liste et au détail."""
    keys = (
        "status", "sanctions_count", "rappels_count", "sanctions_summary", "active_fiches_s_count",
        "active_mute_until", "last_activity_at",
    )
    return {key: summary[key] for key in keys}


async def ai_flag_counts(discord_ids) -> dict[str, dict]:
    """{discord_id: {"total", "open"}} ; jamais d'échec (compteurs à zéro, avertissement)."""
    try:
        return await casier_ai_flags.counts_by_discord_ids(discord_ids)
    except Exception:
        logger.warning("Compteurs des signalements IA indisponibles.", exc_info=True)
        return {}


def _refresh_due(casier: dict, now: datetime) -> bool:
    refreshed_at = _parse_datetime(casier.get("member_refreshed_at"))
    return refreshed_at is None or (now - refreshed_at).total_seconds() >= CASIER_MEMBER_REFRESH_SECONDS


async def build_detail_response(casier: dict, viewer: dict, *, refresh_member: bool) -> CasierDetailResponse:
    """Détail d'un casier. Sans `refresh_member` (routes de modification), aucun appel Discord."""
    now = datetime.now(timezone.utc)
    discord_id = casier.get("discord_id")
    snapshot = casier.get("discord_member_snapshot")
    is_prevention = bool(casier.get("is_prevention", False))

    if refresh_member and _refresh_due(casier, now):
        member, resolved_is_prevention = await resolve_member(discord_id, snapshot, casier_oid=casier.get("_id"))
        if resolved_is_prevention is not None:
            is_prevention = resolved_is_prevention
    else:
        member = member_from_snapshot(snapshot, discord_id)

    casier_id = str(casier["_id"])
    sanctions = [sanction_out(sanction, casier_id, viewer, now) for sanction in _items(casier, "sanctions")]
    sanctions.sort(key=lambda sanction: casier_search.timestamp_of(sanction["created_at"]), reverse=True)
    fiches = [casier_service.fiche_to_out(fiche, viewer) for fiche in _items(casier, "fiches_s")]
    fiches.sort(key=lambda fiche: casier_search.timestamp_of(fiche["created_at"]), reverse=True)
    fiches.sort(key=lambda fiche: not fiche["active"])  # actives d'abord (tri stable)
    flags = (await ai_flag_counts([discord_id])).get(discord_id) or {}

    return CasierDetailResponse(
        id=casier_id,
        member=member,
        created_at=casier.get("created_at") or "",
        created_by=_author_out(casier.get("created_by")),
        sanctions=sanctions,
        fiches_s=fiches,
        is_prevention=is_prevention,
        ai_flags_total=int(flags.get("total") or 0),
        ai_flags_open=int(flags.get("open") or 0),
        **summary_fields(casier_service.summarize(casier, now)),
    )


def list_item(casier: dict, flag_counts: dict, now: datetime) -> dict:
    discord_id = casier.get("discord_id")
    summary = casier_service.summarize(casier, now)
    flags = flag_counts.get(discord_id) or {}
    return {
        "id": str(casier["_id"]),
        "member": member_from_snapshot(casier.get("discord_member_snapshot"), discord_id).model_dump(),
        "has_active_fiche_s": summary["has_active_fiche_s"],
        "last_sanction_at": summary["last_sanction_at"],
        "last_sanction_label": summary["last_sanction_label"],
        "created_at": casier.get("created_at") or "",
        "is_prevention": bool(casier.get("is_prevention", False)),
        "ai_flags_total": int(flags.get("total") or 0),
        "ai_flags_open": int(flags.get("open") or 0),
        "matches": [],
        "matches_total": 0,
        **summary_fields(summary),
    }


async def with_fiche_texts(casier: dict) -> dict:
    """Recharge le contenu des fiches qui n'ont pas encore de `content_text` (non migrées)."""
    missing = any(
        not isinstance(fiche.get("content_text"), str) and "content" not in fiche
        for fiche in _items(casier, "fiches_s")
    )
    if not missing:
        return casier
    full = await db.casiers.find_one({"_id": casier["_id"]}, {"fiches_s.revisions": 0})
    return full or casier


# --- Chargement -------------------------------------------------------------------------------


async def load_casier(casier_id: str, projection: dict | None = None) -> dict:
    object_id = object_id_or_400(casier_id)
    casier = await db.casiers.find_one({"_id": object_id}, projection)
    if not casier:
        raise HTTPException(status_code=404, detail="Casier introuvable.")
    return casier


async def load_casier_for_items(casier_id: str) -> dict:
    """Casier complet avec des ids pour toutes les sanctions et fiches (migration paresseuse)."""
    casier = await load_casier(casier_id)
    return await casier_service.ensure_item_ids(casier)


def find_sanction(casier: dict, sanction_id: str) -> dict:
    return casier["sanctions"][casier_service.sanction_index(casier, sanction_id)]


async def reload_casier(casier: dict) -> dict:
    return await db.casiers.find_one({"_id": casier["_id"]}) or casier


# --- Routes statiques (déclarées avant /{casier_id}) ------------------------------------------


@router.get("/search-members", response_model=list[MemberSearchResult])
async def search_members(
    q: str = Query(..., min_length=1),
    staff=Depends(current_staff),
):
    needle = q.strip()
    if not needle:
        return []

    results = await search_guild_members(needle, limit=10)
    return [MemberSearchResult(**member) for member in results]


@router.get("/bot/{discord_id}", response_model=BotCasierResponse)
async def get_casier_for_bot(
    discord_id: str,
    status_format: str | None = Query(None),
    _: str = Depends(verify_bot_api_key),
):
    """Route dédiée aux bots externes (ex. Ghost Bot) : renvoie l'historique
    des sanctions déjà formaté en markdown, ainsi que la présence ou non
    d'une fiche S active. Ne crée jamais de casier et n'expose pas le
    contenu des fiches S (uniquement leur présence). Statuts : anciennes
    valeurs par défaut (`legacy`), nouvelles avec `v2`."""
    if status_format is not None:
        chosen_format = status_format.strip().lower()
        if chosen_format not in GHOST_BOT_STATUS_FORMATS:
            raise HTTPException(status_code=422, detail="Format de statut inconnu (legacy ou v2).")
    else:
        chosen_format = GHOST_BOT_STATUS_FORMAT if GHOST_BOT_STATUS_FORMAT in GHOST_BOT_STATUS_FORMATS else "legacy"

    discord_id = discord_id_or_422(discord_id)
    casier = await db.casiers.find_one({"discord_id": discord_id})

    if not casier:
        return BotCasierResponse(
            discord_id=discord_id,
            status="vierge",
            sanctions_count=0,
            has_active_fiche_s=False,
            sanctions_markdown="*Aucune sanction enregistrée.*",
        )

    if chosen_format == "v2":
        bot_status = casier_service.compute_status(casier)
    else:
        bot_status = casier_service.compute_legacy_status(casier)

    return BotCasierResponse(
        discord_id=discord_id,
        status=bot_status,
        sanctions_count=len(casier.get("sanctions", [])),
        has_active_fiche_s=casier_service.has_active_fiche_s(casier),
        sanctions_markdown=sanctions_to_markdown(casier),
    )


@router.get("/ai-flags", response_model=AiFlagListResponse)
async def list_ai_flags(
    discord_id: str | None = Query(None),
    q: str | None = Query(None, max_length=100),
    review_status: AiFlagReviewFilter = Query("tous"),
    min_gravity: int | None = Query(None, ge=1, le=3),
    category: str | None = Query(None, max_length=40, pattern=r"^[a-z_]+$"),
    kind: AiFlagKind | None = Query(None),
    skip: int = Query(0, ge=0, le=10_000),
    limit: int = Query(30, ge=1, le=100),
    staff=Depends(current_staff),
):
    filters = {
        "q": (q or "").strip(),
        "review_status": review_status,
        "min_gravity": min_gravity,
        "category": category,
        "kind": kind,
    }
    if discord_id is not None and discord_id.strip():
        filters["discord_id"] = discord_id_or_422(discord_id)
    return await casier_ai_flags.build_list_response(filters, skip, limit)


@router.get("/ai-flags/{flag_id}", response_model=AiFlagOut)
async def get_ai_flag(
    flag_id: str,
    staff=Depends(current_staff),
):
    return await casier_ai_flags.get_flag_out(flag_id)


@router.patch("/ai-flags/{flag_id}", response_model=AiFlagOut)
async def review_ai_flag(
    flag_id: str,
    payload: ReviewAiFlagPayload,
    request: Request,
    staff=Depends(current_staff),
):
    flag_id = casier_ai_flags.flag_id_or_400(flag_id)
    comment = payload.comment if payload.comment_provided else casier_ai_flags.UNCHANGED
    updated, review_before = await casier_ai_flags.review_flag(
        flag_id, payload.review_status, comment, reviewer=casier_service.staff_to_author(staff)
    )

    discord_id = str(updated.get("discord_id") or "")
    casier = None
    if discord_id:
        casier = await db.casiers.find_one(
            {"discord_id": discord_id}, {"discord_id": 1, "discord_member_snapshot": 1}, sort=[("_id", 1)]
        )
    author = updated.get("author") or {}
    member_details = {} if casier else {
        "member_id": discord_id or None,
        "member_username": author.get("display_name") or author.get("username"),
    }
    review = updated.get("review") or {}
    await casier_audit.log_casier_event(
        casier_audit.AI_FLAG_REVIEWED,
        request,
        staff,
        status.HTTP_200_OK,
        casier=casier,
        flag_id=flag_id,
        review_before=review_before,
        review_after=review.get("status") or payload.review_status,
        comment_length=casier_audit.text_length(review.get("comment")),
        **member_details,
    )
    return await casier_ai_flags.flag_out(updated)


# --- Casiers ----------------------------------------------------------------------------------


@router.get("", response_model=list[CasierListItem])
async def list_casiers(
    q: str | None = Query(None, max_length=100),
    scope: SearchScope = Query("tout"),
    status_filter: str | None = Query(None, alias="status", max_length=200),
    has_active_fiche_s: bool | None = Query(None),
    prevention: bool | None = Query(None),
    has_open_ai_flags: bool | None = Query(None),
    sort: CasierSort = Query("recent"),
    staff=Depends(current_staff),
):
    terms = casier_search.parse_terms(q)
    wanted_status = casier_search.parse_status_filter(status_filter)
    now = datetime.now(timezone.utc)

    documents = [casier async for casier in db.casiers.find({}, LIST_PROJECTION) if casier.get("discord_id")]
    flag_counts = await ai_flag_counts([casier["discord_id"] for casier in documents])
    by_id = {str(casier["_id"]): casier for casier in documents}

    items = casier_search.apply_filters(
        [list_item(casier, flag_counts, now) for casier in documents],
        status=wanted_status,
        has_active_fiche_s=has_active_fiche_s,
        prevention=prevention,
        has_open_ai_flags=has_open_ai_flags,
    )

    if terms:
        found = []
        for item in items:
            casier = by_id[item["id"]]
            if casier_migrations.has_missing_ids(casier):
                casier = await casier_service.ensure_item_ids(casier, projection=LIST_PROJECTION)
            if scope in ("tout", "contenu"):
                casier = await with_fiche_texts(casier)
            matched, matches, total = casier_search.search_casier(casier, terms, scope)
            if matched:
                item["matches"] = matches
                item["matches_total"] = total
                found.append(item)
        items = found

    return [CasierListItem(**item) for item in casier_search.sort_items(items, sort)]


@router.post("", response_model=CasierResponse, status_code=status.HTTP_201_CREATED)
async def create_casier(
    payload: CreateCasierPayload,
    request: Request,
    staff=Depends(current_staff),
):
    discord_id = discord_id_or_422(payload.discord_id)
    username = (payload.username or "").strip()

    existing = await db.casiers.find_one({"discord_id": discord_id})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Un casier existe déjà pour ce membre.",
        )

    # Seule route de modification qui interroge Discord, avant toute écriture (le 502 reste voulu).
    guild_member = await fetch_guild_member(discord_id)

    if guild_member:
        snapshot = snapshot_from_guild_member(guild_member)
        is_prevention = False
    else:
        if not username:
            raise HTTPException(
                status_code=404,
                detail="Membre introuvable sur le serveur Discord. Renseigne un pseudo pour créer un casier en prévention.",
            )
        snapshot = {
            "id": discord_id,
            "username": username,
            "display_name": username,
            "avatar_url": None,
        }
        is_prevention = True

    casier = await casier_service.get_or_create_casier(discord_id, snapshot, casier_service.staff_to_author(staff))
    now = casier_service.now_iso()
    await db.casiers.update_one(
        {"_id": casier["_id"]},
        {"$set": {"is_prevention": is_prevention, "member_refreshed_at": now, "updated_at": now}},
    )
    casier["is_prevention"] = is_prevention
    await casier_history.record_creation(casier, staff)

    await casier_audit.log_casier_event(
        casier_audit.CASIER_CREATED,
        request,
        staff,
        status.HTTP_201_CREATED,
        casier=casier,
        is_prevention=is_prevention,
    )

    return CasierResponse(
        id=str(casier["_id"]),
        discord_id=discord_id,
        created_at=casier["created_at"],
    )


@router.get("/{casier_id}", response_model=CasierDetailResponse)
async def get_casier(
    casier_id: str,
    staff=Depends(current_staff),
):
    casier = await load_casier(casier_id)

    if not casier.get("discord_id"):
        raise HTTPException(status_code=500, detail="Casier invalide : discord_id manquant.")

    casier = await casier_service.ensure_item_ids(casier)
    viewer = await viewer_for(staff)
    return await build_detail_response(casier, viewer, refresh_member=True)


# --- Sanctions --------------------------------------------------------------------------------


@router.post("/{casier_id}/sanctions", response_model=CasierDetailResponse, status_code=status.HTTP_201_CREATED)
async def add_sanction_endpoint(
    casier_id: str,
    payload: CreateSanctionPayload,
    request: Request,
    staff=Depends(current_staff),
):
    if payload.type not in casier_service.SANCTION_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Type de sanction invalide. Valeurs autorisées : {sorted(casier_service.SANCTION_TYPES)}",
        )
    flag_id = hex_id_or_400(payload.ai_flag_id) if payload.ai_flag_id is not None else None

    casier = await load_casier(casier_id)
    if not casier.get("discord_id"):
        raise HTTPException(status_code=500, detail="Casier invalide : discord_id manquant.")
    if flag_id:
        # 404 / 422 / 409 avant toute écriture.
        await casier_ai_flags.check_linkable(flag_id, casier["discord_id"])

    duration_label, duration_seconds = None, None
    if payload.type in casier_service.DURATION_TYPES and payload.duration:
        duration_label, duration_seconds = casier_log_parser.parse_duration_text(payload.duration)

    viewer = await viewer_for(staff)
    author = casier_service.staff_to_author(staff)
    status_before = casier_service.compute_status(casier)
    sanction_id = casier_service.new_id()
    history_before = casier_history.capture(casier, "sanction", sanction_id)

    updated = await casier_service.add_sanction(
        casier["discord_id"],
        payload.type,
        payload.reason,
        casier.get("discord_member_snapshot") or {},
        created_by=author,
        duration=duration_label,
        sanction_id=sanction_id,
        duration_seconds=duration_seconds,
        ai_flag_id=flag_id,
        moderator=None,
    )
    await casier_history.record_change(history_before, updated, action=casier_history.ACTION_CREATED, staff=staff)

    link = None
    if flag_id:
        link = await casier_ai_flags.link_sanction(flag_id, str(updated["_id"]), sanction_id, reviewer=author)

    await casier_audit.log_casier_event(
        casier_audit.SANCTION_CREATED,
        request,
        staff,
        status.HTTP_201_CREATED,
        casier=updated,
        sanction_id=sanction_id,
        sanction_type=payload.type,
        reason_excerpt=casier_audit.excerpt(payload.reason),
        duration=duration_label,
        status_before=status_before,
        status_after=casier_service.compute_status(updated),
        ai_flag_id=flag_id,
    )
    if link and link.get("review_changed"):
        flag = await casier_ai_flags.get_flag(flag_id) or {}
        await casier_audit.log_casier_event(
            casier_audit.AI_FLAG_REVIEWED,
            request,
            staff,
            status.HTTP_200_OK,
            casier=updated,
            flag_id=flag_id,
            review_before=link.get("review_before"),
            review_after=link.get("review_after"),
            comment_length=casier_audit.text_length((flag.get("review") or {}).get("comment")),
        )

    return await build_detail_response(updated, viewer, refresh_member=False)


# --- Informations complémentaires -------------------------------------------------------------


@router.post(
    "/{casier_id}/sanctions/{sanction_id}/notes",
    response_model=CasierDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_note_endpoint(
    casier_id: str,
    sanction_id: str,
    payload: NotePayload,
    request: Request,
    staff=Depends(current_staff),
):
    object_id_or_400(casier_id)
    hex_id_or_400(sanction_id)
    casier = await load_casier_for_items(casier_id)
    viewer = await viewer_for(staff)

    history_before = casier_history.capture(casier, "sanction", sanction_id)
    updated, details = await casier_service.add_note(
        casier, sanction_id, payload.content, casier_service.staff_to_author(staff)
    )
    await casier_history.record_change(history_before, updated, action=casier_history.ACTION_NOTE_ADDED, staff=staff)

    await casier_audit.log_casier_event(
        casier_audit.NOTE_CREATED, request, staff, status.HTTP_201_CREATED, casier=updated, **details
    )
    return await build_detail_response(updated, viewer, refresh_member=False)


@router.patch(
    "/{casier_id}/sanctions/{sanction_id}/notes/{note_id}",
    response_model=CasierDetailResponse,
)
async def update_note_endpoint(
    casier_id: str,
    sanction_id: str,
    note_id: str,
    payload: NotePayload,
    request: Request,
    staff=Depends(current_staff),
):
    object_id_or_400(casier_id)
    hex_id_or_400(sanction_id)
    hex_id_or_400(note_id)
    casier = await load_casier_for_items(casier_id)
    viewer = await viewer_for(staff)

    # 404 (sanction, information) et 403 (ni auteur ni Responsable) levés par le service.
    history_before = casier_history.capture(casier, "sanction", sanction_id)
    updated, details = await casier_service.update_note(
        casier, sanction_id, note_id, payload.content, casier_service.staff_to_author(staff), viewer=viewer
    )
    await casier_history.record_change(history_before, updated, action=casier_history.ACTION_NOTE_UPDATED, staff=staff)

    await casier_audit.log_casier_event(
        casier_audit.NOTE_UPDATED, request, staff, status.HTTP_200_OK, casier=updated, **details
    )
    return await build_detail_response(updated, viewer, refresh_member=False)


@router.delete(
    "/{casier_id}/sanctions/{sanction_id}/notes/{note_id}",
    response_model=CasierDetailResponse,
)
async def delete_note_endpoint(
    casier_id: str,
    sanction_id: str,
    note_id: str,
    request: Request,
    staff=Depends(current_staff),
):
    object_id_or_400(casier_id)
    hex_id_or_400(sanction_id)
    hex_id_or_400(note_id)
    casier = await load_casier_for_items(casier_id)
    viewer = await viewer_for(staff)

    history_before = casier_history.capture(casier, "sanction", sanction_id)
    updated, details = await casier_service.delete_note(
        casier, sanction_id, note_id, casier_service.staff_to_author(staff), viewer=viewer
    )
    await casier_history.record_change(history_before, updated, action=casier_history.ACTION_NOTE_DELETED, staff=staff)

    await casier_audit.log_casier_event(
        casier_audit.NOTE_DELETED, request, staff, status.HTTP_200_OK, casier=updated, **details
    )
    return await build_detail_response(updated, viewer, refresh_member=False)


# --- Fichiers ---------------------------------------------------------------------------------


@router.post(
    "/{casier_id}/sanctions/{sanction_id}/attachments/resync",
    response_model=CasierDetailResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resync_attachments_endpoint(
    casier_id: str,
    sanction_id: str,
    request: Request,
    staff=Depends(current_staff),
):
    object_id_or_400(casier_id)
    hex_id_or_400(sanction_id)
    casier = await load_casier_for_items(casier_id)
    sanction = find_sanction(casier, sanction_id)
    viewer = await viewer_for(staff)

    # Relit le message de log sur Discord avant toute écriture (409 sans log ou copie en cours, 502).
    result = await casier_attachments.resync_from_discord(casier, sanction, resolve_author=resolve_log_author)
    if result.get("files_queued"):
        try:
            casier_attachments.schedule_mirror(str(casier["_id"]), sanction_id)
        except Exception:
            logger.exception("Copie des fichiers non planifiée (casier %s, sanction %s).", casier["_id"], sanction_id)

    updated = await reload_casier(casier)
    await casier_audit.log_casier_event(
        casier_audit.ATTACHMENTS_RESYNCED,
        request,
        staff,
        status.HTTP_202_ACCEPTED,
        casier=updated,
        **casier_audit.sanction_context(sanction),
        files_found=int(result.get("files_found") or 0),
        files_queued=int(result.get("files_queued") or 0),
        moderator_filled=bool(result.get("moderator_filled")),
    )
    return await build_detail_response(updated, viewer, refresh_member=False)


@router.post(
    "/{casier_id}/sanctions/{sanction_id}/attachments",
    response_model=CasierDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment_endpoint(
    casier_id: str,
    sanction_id: str,
    request: Request,
    file: UploadFile = File(...),
    staff=Depends(current_staff),
):
    object_id_or_400(casier_id)
    hex_id_or_400(sanction_id)
    casier = await load_casier_for_items(casier_id)
    sanction = find_sanction(casier, sanction_id)
    viewer = await viewer_for(staff)

    # Format, signature, taille (lecture en flux) et nombre de fichiers vérifiés par le service.
    attachment = await casier_attachments.save_upload(
        casier, sanction_id, file, casier_service.staff_to_author(staff)
    )

    updated = await reload_casier(casier)
    await casier_audit.log_casier_event(
        casier_audit.ATTACHMENT_UPLOADED,
        request,
        staff,
        status.HTTP_201_CREATED,
        casier=updated,
        **casier_audit.sanction_context(sanction),
        attachment_id=attachment.get("id"),
        original_filename=attachment.get("filename"),
        size=attachment.get("size"),
    )
    return await build_detail_response(updated, viewer, refresh_member=False)


@router.get("/{casier_id}/sanctions/{sanction_id}/attachments/{attachment_id}")
async def get_attachment_endpoint(
    casier_id: str,
    sanction_id: str,
    attachment_id: str,
    request: Request,
    download: bool = Query(False),
    staff=Depends(current_staff),
):
    object_id_or_400(casier_id)
    hex_id_or_400(sanction_id)
    attachment_id_or_400(attachment_id)
    casier = await load_casier(casier_id, {"fiches_s": 0})
    sanction = find_sanction(casier, sanction_id)
    attachment = casier_attachments.find_attachment(sanction, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Fichier introuvable.")
    # Inline seulement pour png/jpeg/gif/webp (extension ET type), sinon téléchargement.
    return casier_attachments.stream_attachment(request, str(casier["_id"]), sanction_id, attachment, download=download)


@router.delete(
    "/{casier_id}/sanctions/{sanction_id}/attachments/{attachment_id}",
    response_model=CasierDetailResponse,
)
async def delete_attachment_endpoint(
    casier_id: str,
    sanction_id: str,
    attachment_id: str,
    request: Request,
    staff=Depends(current_staff),
):
    object_id_or_400(casier_id)
    hex_id_or_400(sanction_id)
    attachment_id_or_400(attachment_id)
    casier = await load_casier_for_items(casier_id)
    sanction = find_sanction(casier, sanction_id)
    viewer = await viewer_for(staff)

    # 404, 409 (fichier Discord) et 403 (ni auteur ni Responsable) levés par le service.
    removed = await casier_attachments.delete_upload(
        casier, sanction_id, attachment_id, viewer, casier_service.staff_to_author(staff)
    )

    updated = await reload_casier(casier)
    await casier_audit.log_casier_event(
        casier_audit.ATTACHMENT_DELETED,
        request,
        staff,
        status.HTTP_200_OK,
        casier=updated,
        **casier_audit.sanction_context(sanction),
        attachment_id=attachment_id,
        original_filename=removed.get("filename"),
    )
    return await build_detail_response(updated, viewer, refresh_member=False)


# --- Fiches S ---------------------------------------------------------------------------------


@router.post("/{casier_id}/fiches-s", response_model=CasierDetailResponse, status_code=status.HTTP_201_CREATED)
async def add_fiche_s_endpoint(
    casier_id: str,
    payload: CreateFicheSPayload,
    request: Request,
    staff=Depends(current_staff),
):
    casier = await load_casier(casier_id)
    if not casier.get("discord_id"):
        raise HTTPException(status_code=500, detail="Casier invalide : discord_id manquant.")
    viewer = await viewer_for(staff)
    fiche_id = casier_service.new_id()
    history_before = casier_history.capture(casier, "fiche", fiche_id)

    # Contenu assaini et texte extrait par le service ; 422 « La fiche S est vide. » avant écriture.
    updated = await casier_service.add_fiche_s(
        discord_id=casier["discord_id"],
        title=payload.title,
        content=payload.content,
        snapshot=casier.get("discord_member_snapshot") or {},
        created_by=casier_service.staff_to_author(staff),
        fiche_id=fiche_id,
    )
    await casier_history.record_change(history_before, updated, action=casier_history.ACTION_CREATED, staff=staff)

    fiche = next((item for item in _items(updated, "fiches_s") if item.get("id") == fiche_id), {})
    await casier_audit.log_casier_event(
        casier_audit.FICHE_S_CREATED,
        request,
        staff,
        status.HTTP_201_CREATED,
        casier=updated,
        fiche_id=fiche_id,
        fiche_title=fiche.get("title") or payload.title,
        content_length=casier_audit.text_length(fiche.get("content_text")),
    )
    return await build_detail_response(updated, viewer, refresh_member=False)


@router.patch("/{casier_id}/fiches-s/{fiche_id}/close", response_model=CasierDetailResponse)
async def close_fiche_s_endpoint(
    casier_id: str,
    fiche_id: str,
    request: Request,
    staff=Depends(current_staff),
):
    object_id = object_id_or_400(casier_id)
    hex_id_or_400(fiche_id)
    viewer = await viewer_for(staff)
    history_before = casier_history.capture(await db.casiers.find_one({"_id": object_id}), "fiche", fiche_id)
    updated = await casier_service.close_fiche_s(object_id, fiche_id, casier_service.staff_to_author(staff))

    if updated is None:
        raise HTTPException(status_code=404, detail="Casier ou fiche S introuvable, ou déjà clôturée.")
    await casier_history.record_change(history_before, updated, action=casier_history.ACTION_CLOSED, staff=staff)

    fiche = next((item for item in _items(updated, "fiches_s") if item.get("id") == fiche_id), {})
    await casier_audit.log_casier_event(
        casier_audit.FICHE_S_CLOSED,
        request,
        staff,
        status.HTTP_200_OK,
        casier=updated,
        fiche_id=fiche_id,
        fiche_title=fiche.get("title"),
    )
    return await build_detail_response(updated, viewer, refresh_member=False)


@router.patch("/{casier_id}/fiches-s/{fiche_id}", response_model=CasierDetailResponse)
async def update_fiche_s_endpoint(
    casier_id: str,
    fiche_id: str,
    payload: UpdateFicheSPayload,
    request: Request,
    staff=Depends(current_staff),
):
    object_id_or_400(casier_id)
    hex_id_or_400(fiche_id)
    if payload.is_empty():
        raise HTTPException(status_code=422, detail="Rien à modifier.")

    casier = await load_casier_for_items(casier_id)
    viewer = await viewer_for(staff)

    history_before = casier_history.capture(casier, "fiche", fiche_id)
    # 404, 403 (auteur ou Responsable ; clôturée : Responsable) et 422 (fiche vide) levés par le service.
    updated, changed, details = await casier_service.update_fiche_s(
        casier, fiche_id, payload.title, payload.content, casier_service.staff_to_author(staff), viewer=viewer
    )

    if changed:
        await casier_history.record_change(history_before, updated, action=casier_history.ACTION_UPDATED, staff=staff)
        await casier_audit.log_casier_event(
            casier_audit.FICHE_S_UPDATED, request, staff, status.HTTP_200_OK, casier=updated, **details
        )
    return await build_detail_response(updated, viewer, refresh_member=False)
