import csv
import io
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from database import db
from models.audit import AuthLogListResponse, AuthLogSummary
from models.ticket import AuthenticatedHelper
from services.auth_service import current_responsable

router = APIRouter(prefix="/responsable", tags=["responsable"])

PARIS = ZoneInfo("Europe/Paris")
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
MIN_YEAR, MAX_YEAR = 2000, 2100  # évite les dépassements de datetime sur des saisies absurdes

# Catégories du journal (clés acceptées par `categories`) → filtre sur `event_type`.
# « autres » = tout ce qui n'entre dans aucune des catégories nommées.
CATEGORY_CLAUSES = {
    "connexions": {"event_type": {"$regex": r"^auth\.(?:login\.|session\.|logout$)"}},
    "acces_refuses": {"event_type": {"$in": ["authz.forbidden", "auth.login.failure"]}},
    "casiers": {"event_type": {"$regex": r"^casier\."}},
    "annonces": {"event_type": {"$regex": r"^announcement\."}},
    "projets": {"event_type": {"$regex": r"^project\."}},
    "tickets": {"event_type": {"$regex": r"^(ticket|casework|verification)\."}},
}
CATEGORY_KEYS = (*CATEGORY_CLAUSES, "autres")

# Champs de `details` interrogés par la recherche `q` (liste fermée : MongoDB ne sait pas filtrer
# « toutes les valeurs texte d'un sous-document » sans $expr, que mongomock ne gère pas bien).
# Source : routers/animateur.py, routers/auth.py, services/auth_service.py et services/casier_audit.py.
SEARCH_DETAIL_FIELDS = (
    "announcement_id", "publication_id", "asset_id", "channel_id", "command_id", "role_id",
    "ticket_id",
    "helper_id",
    "previous_helper_id",
    "member_id",
    "member_username",
    "casier_id",
    "sanction_id",
    "sanction_type",
    "reason_excerpt",
    "fiche_id",
    "fiche_title",
    "flag_id",
    "ai_flag_id",
    "attachment_id",
    "original_filename",
    "project_id",
    "task_id",
    "resource_id",
    "assignee_id",
    "title",
    "before.title",
    "after.title",
    "provider",
    "mode",
    "reason",
)


def _parse_day(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{name} invalide : format AAAA-MM-JJ attendu.")
    if not MIN_YEAR <= day.year <= MAX_YEAR:
        raise HTTPException(status_code=422, detail=f"{name} invalide : année hors limites.")
    return day


def _paris_midnight_utc(day: date) -> datetime:
    """Minuit (heure de Paris) de ce jour, converti en UTC (created_at est stocké en UTC)."""
    return datetime.combine(day, time.min, tzinfo=PARIS).astimezone(timezone.utc)


def _parse_categories(raw: str | None) -> list[str]:
    keys: list[str] = []
    for part in (raw or "").split(","):
        key = part.strip().lower()
        if not key:
            continue
        if key not in CATEGORY_KEYS:
            raise HTTPException(status_code=422, detail=f"Catégorie inconnue : {key[:40]}.")
        if key not in keys:
            keys.append(key)
    return keys


def _category_filter(keys: list[str]) -> dict | None:
    clauses = []
    for key in keys:
        if key == "autres":
            clauses.append({"$nor": list(CATEGORY_CLAUSES.values())})
        else:
            clauses.append(CATEGORY_CLAUSES[key])
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$or": clauses}


def _search_filter(text: str) -> dict:
    pattern = {"$regex": re.escape(text), "$options": "i"}
    fields = ("username", "helper_id", *(f"details.{name}" for name in SEARCH_DETAIL_FIELDS))
    return {"$or": [{field: pattern} for field in fields]}


def _build_filters(event_type, helper_id, q, categories, date_from, date_to) -> dict:
    filters: dict = {}
    if event_type:
        filters["event_type"] = event_type
    if helper_id:
        filters["helper_id"] = helper_id

    conditions = []

    text = (q or "").strip()
    if text:
        conditions.append(_search_filter(text))

    category_filter = _category_filter(_parse_categories(categories))
    if category_filter:
        conditions.append(category_filter)

    first_day = _parse_day(date_from, "date_from")
    last_day = _parse_day(date_to, "date_to")
    if first_day and last_day and first_day > last_day:
        raise HTTPException(status_code=422, detail="date_from doit précéder date_to.")
    period: dict = {}
    if first_day:
        period["$gte"] = _paris_midnight_utc(first_day)
    if last_day:
        period["$lt"] = _paris_midnight_utc(last_day + timedelta(days=1))
    if period:
        filters["created_at"] = period

    if conditions:
        filters["$and"] = conditions
    return filters


@router.get("/auth-logs", response_model=AuthLogListResponse)
async def list_auth_logs(
    _: AuthenticatedHelper = Depends(current_responsable),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    event_type: str | None = Query(None, max_length=100),
    helper_id: str | None = Query(None, max_length=64),
    q: str | None = Query(None, max_length=100),
    categories: str | None = Query(None, max_length=200),
    date_from: str | None = Query(None, pattern=DATE_PATTERN),
    date_to: str | None = Query(None, pattern=DATE_PATTERN),
):
    filters = _build_filters(event_type, helper_id, q, categories, date_from, date_to)

    total = await db.auth_logs.count_documents(filters)
    items = (
        await db.auth_logs
        .find(filters, {"_id": 0})
        .sort([("created_at", -1), ("_id", -1)])
        .skip(skip)
        .limit(limit)
        .to_list(limit)
    )

    return {"total": total, "items": items}


EXPORT_MAX_ROWS = 10000
EXPORT_COLUMNS = ("created_at", "username", "helper_id", "event_type", "ip", "method", "path", "status_code", "details")


def _csv_safe(value) -> str:
    """Neutralise l'injection de formule tableur (= + - @ en début de cellule)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/auth-logs/export")
async def export_auth_logs(
    _: AuthenticatedHelper = Depends(current_responsable),
    event_type: str | None = Query(None, max_length=100),
    helper_id: str | None = Query(None, max_length=64),
    q: str | None = Query(None, max_length=100),
    categories: str | None = Query(None, max_length=200),
    date_from: str | None = Query(None, pattern=DATE_PATTERN),
    date_to: str | None = Query(None, pattern=DATE_PATTERN),
):
    """CSV de tous les événements correspondant aux filtres de la page (10 000 lignes au plus)."""
    filters = _build_filters(event_type, helper_id, q, categories, date_from, date_to)
    rows = (
        await db.auth_logs
        .find(filters, {"_id": 0})
        .sort([("created_at", -1), ("_id", -1)])
        .limit(EXPORT_MAX_ROWS)
        .to_list(EXPORT_MAX_ROWS)
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(EXPORT_COLUMNS)
    for row in rows:
        created = row.get("created_at")
        if isinstance(created, datetime):
            created = (created if created.tzinfo else created.replace(tzinfo=timezone.utc)).isoformat()
        details = row.get("details") or {}
        writer.writerow([
            _csv_safe(created),
            _csv_safe(row.get("username")),
            _csv_safe(row.get("helper_id")),
            _csv_safe(row.get("event_type")),
            _csv_safe(row.get("ip")),
            _csv_safe(row.get("method")),
            _csv_safe(row.get("path")),
            _csv_safe(row.get("status_code")),
            _csv_safe(json.dumps(details, ensure_ascii=False, default=str) if details else ""),
        ])
    headers = {
        "Content-Disposition": 'attachment; filename="journal-activite.csv"',
        "X-Export-Truncated": "1" if len(rows) >= EXPORT_MAX_ROWS else "0",
        "Cache-Control": "no-store",
    }
    return Response("\ufeff" + buffer.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.get("/auth-logs/summary", response_model=AuthLogSummary)
async def auth_logs_summary(_: AuthenticatedHelper = Depends(current_responsable)):
    """Compteurs de la journée en cours (jour calendaire Europe/Paris)."""
    today = datetime.now(PARIS).date()
    period = {
        "$gte": _paris_midnight_utc(today),
        "$lt": _paris_midnight_utc(today + timedelta(days=1)),
    }

    async def count(event_filter: dict) -> int:
        return await db.auth_logs.count_documents({"created_at": period, **event_filter})

    return {
        "date": today.isoformat(),
        "access_denied": await count({"event_type": "authz.forbidden"}),
        "login_success": await count({"event_type": "auth.login.success"}),
        "login_failure": await count({"event_type": "auth.login.failure"}),
        "casier_changes": await count(CATEGORY_CLAUSES["casiers"]),
    }
