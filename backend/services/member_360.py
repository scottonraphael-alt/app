"""Vue membre à 360° (lecture seule) : agrège casier, signalements IA, fiches S, informations et tickets.

Droits par type, appliqués ici avant toute lecture en base : un type non autorisé n'est jamais
interrogé, donc ne peut pas fuiter (ni contenu, ni compteur, ni existence).
- sanction / fiche / note / ai_flag : accès casier (rôle Staff, comme `routers/casier.py`) ;
- ticket : rôle Helper (admins inclus) ou Responsable, et seulement {id, date, statut, helper, niveau}.
Aucun contenu de ticket, de fiche S (corps) ni de message signalé n'est renvoyé.
"""
import logging
import re
from datetime import datetime, timezone

from database import db
from services import casier_audit, casier_service

logger = logging.getLogger(__name__)

DISCORD_ID_PATTERN = re.compile(r"[0-9]{17,20}")
DETAIL_MAX = 140
SOURCE_CAP = 500  # documents lus par source
DEFAULT_LIMIT = 30
MAX_LIMIT = 100

CASIER_TYPES = ("sanction", "ai_flag", "fiche", "note")
SANCTION_SEVERITY = {
    "rappel_a_lordre": "info",
    "avertissement": "low",
    "mute": "medium",
    "kick": "high",
    "bannissement": "critical",
}
TICKET_SEVERITY = {"routine": "info", "prioritaire": "medium", "urgent": "high"}
SANCTION_LABELS = {
    "rappel_a_lordre": "Rappel à l'ordre",
    "avertissement": "Avertissement",
    "mute": "Mute",
    "kick": "Kick",
    "bannissement": "Bannissement",
}
AI_KIND_LABELS = {"violation": "Violation", "refus": "Refus du modèle", "illisible": "Réponse illisible"}
AI_SEVERITY = {0: "info", 1: "low", 2: "medium", 3: "high"}

CASIER_PROJECTION = {"fiches_s.content": 0, "fiches_s.revisions": 0, "sanctions.attachments": 0}
TICKET_PROJECTION = {
    "_id": 0, "id": 1, "created_at": 1, "status": 1, "priority": 1, "assigned_helper": 1, "member": 1,
}


def parse_moment(value) -> datetime | None:
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


def _text(value) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _short(value) -> str:
    return casier_audit.excerpt(value, DETAIL_MAX)


def _person(value) -> str | None:
    if not isinstance(value, dict):
        return None
    return _text(value.get("display_name")) or _text(value.get("username")) or _text(value.get("id"))


def _entry(kind: str, ident, moment: datetime, title: str, detail: str, url: str, severity: str) -> dict:
    return {
        "type": kind, "id": str(ident), "at": moment.isoformat(), "title": title,
        "detail": detail, "url": url, "severity": severity, "_moment": moment,
    }


def casier_url(casier_id, **params) -> str:
    query = "&".join(f"{key}={value}" for key, value in (("casier", casier_id), *params.items()))
    return f"/moderation/casiers?{query}"


# --------------------------------------------------------------------------- casier


async def load_casier_entries(discord_id: str) -> dict:
    """Sanctions, fiches S, informations et signalements IA du membre (accès casier requis)."""
    entries: list[dict] = []
    casiers = await db.casiers.find({"discord_id": discord_id}, CASIER_PROJECTION).to_list(5)
    sanctions_total = fiches_total = 0
    snapshot = None
    worst = {"discord_id": discord_id, "sanctions": []}
    for casier in casiers:
        snapshot = snapshot or (casier.get("discord_member_snapshot") if isinstance(casier.get("discord_member_snapshot"), dict) else None)
        casier_id = casier.get("_id")
        worst["sanctions"].extend(casier_service._items(casier, "sanctions"))
        for sanction in casier_service._items(casier, "sanctions"):
            sanctions_total += 1
            sanction_id = sanction.get("id") or ""
            kind = sanction.get("type") if isinstance(sanction.get("type"), str) else "sanction"
            moment = parse_moment(sanction.get("created_at"))
            if moment:
                duration = f" ({sanction['duration']})" if sanction.get("duration") else ""
                entries.append(_entry(
                    "sanction", sanction_id, moment,
                    SANCTION_LABELS.get(kind, "Sanction") + duration,
                    _short(sanction.get("reason")),
                    casier_url(casier_id, sanction=sanction_id),
                    SANCTION_SEVERITY.get(kind, "low"),
                ))
            for note in casier_service.visible_notes(sanction):
                note_moment = parse_moment(note.get("created_at"))
                if note_moment:
                    entries.append(_entry(
                        "note", note.get("id") or "", note_moment, "Information ajoutée",
                        _short(note.get("content")), casier_url(casier_id, sanction=sanction_id), "info",
                    ))
        for fiche in casier_service._items(casier, "fiches_s"):
            fiches_total += 1
            moment = parse_moment(fiche.get("created_at"))
            if moment:
                active = bool(fiche.get("active"))
                entries.append(_entry(
                    "fiche", fiche.get("id") or "", moment, "Fiche S" + ("" if active else " (clôturée)"),
                    _short(fiche.get("title")), casier_url(casier_id), "high" if active else "low",
                ))
    flags = await db.ai_moderation_flags.find(
        {"discord_id": discord_id},
        {"_id": 0, "id": 1, "created_at": 1, "kind": 1, "verdict": 1, "author": 1},
    ).sort("created_at", -1).to_list(SOURCE_CAP)
    flags_total = await db.ai_moderation_flags.count_documents({"discord_id": discord_id})
    for flag in flags:
        moment = parse_moment(flag.get("created_at"))
        if not moment:
            continue
        verdict = flag.get("verdict") if isinstance(flag.get("verdict"), dict) else {}
        kind = flag.get("kind")
        gravite = verdict.get("gravite") if isinstance(verdict.get("gravite"), int) else 0
        detail = verdict.get("raison") or verdict.get("categorie") or ""
        entries.append(_entry(
            "ai_flag", flag.get("id") or "", moment,
            "Signalement IA : " + AI_KIND_LABELS.get(kind, "alerte"), _short(detail),
            f"/moderation/casiers?signalement={flag.get('id')}",
            AI_SEVERITY.get(gravite, "info") if kind == "violation" else "info",
        ))
        snapshot = snapshot or (flag.get("author") if isinstance(flag.get("author"), dict) else None)
    return {
        "entries": entries,
        "status": casier_service.compute_status(worst),
        "sanctions_count": sanctions_total,
        "fiches_count": fiches_total,
        "ai_flags_count": flags_total,
        "snapshot": snapshot,
    }


# --------------------------------------------------------------------------- tickets


async def load_ticket_entries(discord_id: str) -> dict:
    """Tickets du membre : uniquement {id, date, statut, helper, niveau}, jamais le contenu."""
    query = {
        "$and": [
            {"$or": [{"member.id": discord_id}, {"member_id": discord_id}]},
            {"demo_ticket": {"$ne": True}},
        ]
    }
    tickets = await db.tickets.find(query, TICKET_PROJECTION).sort("created_at", -1).to_list(SOURCE_CAP)
    entries = []
    member = None
    for ticket in tickets:
        moment = parse_moment(ticket.get("created_at"))
        member = member or (ticket.get("member") if isinstance(ticket.get("member"), dict) else None)
        if not moment:
            continue
        level = ticket.get("priority") if ticket.get("priority") in TICKET_SEVERITY else "routine"
        status = ticket.get("status") if ticket.get("status") in ("active", "archived") else "active"
        helper = _person(ticket.get("assigned_helper")) or "non assigné"
        entries.append(_entry(
            "ticket", ticket.get("id") or "", moment, "Ticket d'écoute",
            _short(f"Statut : {status} · Helper : {helper} · Niveau : {level}"),
            f"/tickets/{ticket.get('id')}", TICKET_SEVERITY[level],
        ))
    count = await db.tickets.count_documents(query)
    return {"entries": entries, "tickets_count": count, "member": member}


# --------------------------------------------------------------------------- assemblage


def member_out(discord_id: str, *sources) -> dict:
    out = {"id": discord_id, "username": discord_id, "display_name": None, "avatar_url": None}
    for source in sources:
        if not isinstance(source, dict):
            continue
        out["username"] = _text(source.get("username")) or out["username"]
        out["display_name"] = _text(source.get("display_name")) or out["display_name"]
        out["avatar_url"] = _text(source.get("avatar_url")) or out["avatar_url"]
        if source.get("joined_at") and "joined_at" not in out:
            out["joined_at"] = _text(source.get("joined_at"))
        break
    return out


async def build_member_360(
    discord_id: str, *, can_casier: bool, can_tickets: bool, before: datetime | None, limit: int, case_roles=None
) -> dict:
    """Réponse complète ; `can_*` filtrent AVANT la lecture. Lève ValueError si aucun droit."""
    if not (can_casier or can_tickets or case_roles):
        raise ValueError("no access")
    casier = await load_casier_entries(discord_id) if can_casier else None
    tickets = await load_ticket_entries(discord_id) if can_tickets else None

    entries = (casier["entries"] if casier else []) + (tickets["entries"] if tickets else [])
    cases = forms = None
    if case_roles is not None:
        from services.casework import timeline, policy
        from services import verification_timeline
        settings = policy.Settings()
        if settings.enabled:
            cursor = (before if before.tzinfo else before.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat() if before else None
            cases = await timeline.entries(discord_id, case_roles, settings, before=cursor, limit=limit + 1)
            allowed = policy.can_read(set(case_roles), {'kind': 'verification', 'visibility': 'staff'})
            forms = await verification_timeline.entries(discord_id, can_verifications=allowed)
            for source in (cases, forms):
                for entry in (source or {}).get('entries', []):
                    moment = datetime.fromisoformat(entry['at'].replace('Z', '+00:00'))
                    entries.append({**entry, '_moment': moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)})
    entries.sort(key=lambda item: (item["_moment"], item["id"]), reverse=True)
    last_activity = entries[0]["at"] if entries else None
    if before is not None:
        before = before if before.tzinfo else before.replace(tzinfo=timezone.utc)
        entries = [item for item in entries if item["_moment"] < before]
    page = entries[:limit]
    next_before = page[-1]["at"] if len(entries) > limit and page else None
    timeline = [{key: value for key, value in item.items() if key != "_moment"} for item in page]

    member = member_out(discord_id, casier["snapshot"] if casier else None, tickets["member"] if tickets else None)
    if tickets and isinstance(tickets["member"], dict) and tickets["member"].get("joined_at"):
        member["joined_at"] = _text(tickets["member"]["joined_at"])
    summary = {
        "status": casier["status"] if casier else None,
        "sanctions_count": casier["sanctions_count"] if casier else None,
        "ai_flags_count": casier["ai_flags_count"] if casier else None,
        "tickets_count": tickets["tickets_count"] if tickets else None,
        "fiches_count": casier["fiches_count"] if casier else None,
        "last_activity_at": last_activity,
    }
    if cases is not None: summary["case_tickets_count"] = cases["count"]
    if forms is not None: summary["verification_forms_count"] = forms["count"]
    return {"member": member, "summary": summary, "timeline": timeline, "next_before": next_before}
