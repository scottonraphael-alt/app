"""Réunions de l'agenda (`meeting_summaries`) : lecture tolérante, phases, contenu BlockNote, écritures.

- Lecture tolérante des anciens documents (`normalize_meeting`) : ordre du jour en texte, contenu en texte
  brut, sans `revision` ni nouveaux champs. Rien n'est écrit tant que personne ne modifie.
- Contenu : `prepare_content` nettoie le JSON BlockNote (liens, médias, profondeur 20) et en extrait le
  texte ; rien d'autre qu'une 422 « Contenu illisible. » ne peut en sortir. Le contenu est aussi nettoyé
  à la lecture (`to_detail`), pour les documents écrits avant la refonte.
- Écritures concurrentes : `patch` écrit avec un filtre de révision et de verrouillage (409 / 403) ; ni le
  cochage d'une action ni le verrouillage ne changent `revision`.
- Les listes (liste, vue d'ensemble) lisent avec `MEETING_SUMMARY_PROJECTION`, jamais le contenu.
- Les rappels sont synchronisés par l'appelant (`agenda_reminders`), après l'écriture.
"""
import json
import logging
import math
import re
import unicodedata
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi.responses import JSONResponse
from pydantic import BaseModel

from database import db
from models.staff import (
    MeetingCreateIn,
    MeetingPatch,
    RevisionConflictOut,
    null_required_message,
)
from services import agenda_people, agenda_time
from services.notifications import create_notification
from services.agenda_absences import (
    forbidden,
    identity,
    is_valid_id,
    iso_or_none,
    iso_z_or_none,
    not_found,
    session_identity,
    unprocessable,
    viewer_info,
    viewer_out,
)
from services.agenda_entries import (
    PING_FORBIDDEN,
    merge_reminders,
    reminder_info,
    reminders_from_input,
    stored_reminders,
)

logger = logging.getLogger(__name__)

MEETING_SUMMARY_PROJECTION = {"_id": 0, "content_markdown": 0, "content_text": 0, "search_text": 0}

NOT_FOUND = "Réunion introuvable."
ACTION_NOT_FOUND = "Action introuvable."
LOCKED = "Ce résumé est verrouillé."
RESERVED_FORBIDDEN = "Seul un responsable peut modifier la date, les participants, les rappels ou l'annulation."
CONFLICT_MESSAGE = "Ce compte-rendu a été modifié par quelqu'un d'autre. Rechargez avant de continuer."
MSG_UNREADABLE = "Contenu illisible."
MSG_START_TIME_REQUIRED = "Indiquez une heure de début."
MSG_END_TIME_ORDER = "L'heure de fin doit suivre l'heure de début."
MSG_OUT_OF_BOUNDS = "Date hors limites."
MSG_INVALID_PHASE = "Filtre de phase inconnu."

# Champs du PATCH réservés aux responsables, et ceux qui replanifient les rappels.
RESERVED_FIELDS = frozenset({
    "meeting_date", "start_time", "end_time", "location", "participant_ids", "reminders", "cancelled",
    "cancel_reason",
})
SCHEDULE_FIELDS = frozenset({"meeting_date", "start_time", "end_time", "reminders", "cancelled"})
PHASES = ("a_venir", "a_rediger", "redige", "annulee")
ATTENDANCES = ("invite", "present", "absent", "excuse")
STATUS_WRITTEN = "redige"
STATUS_PENDING = "en_attente_resume"

PAST_DAYS = 366
FUTURE_DAYS = 731
MAX_DEPTH = 20
CONTENT_TEXT_MAX = 100_000
SEARCH_TEXT_MAX = 20_000
EXCERPT_MAX = 220
AGENDA_TEXT_MAX = 4000
AGENDA_TITLE_MAX = 200
LIST_ITEMS_MAX = 50
AGENDA_PREVIEW_MAX = 5
SCAN_LIMIT = 2000
LIST_LIMIT_MAX = 200
TO_WRITE_MAX = 10
OPEN_ACTIONS_MAX = 50

LEGACY_BULLET = re.compile(r"^\s*(\d+[.)]|[-•*])\s*")
WORD_RE = re.compile(r"\S+")
# Liens : web, courriel ou chemin du site (ni « //hôte » ni « /\hôte », lus comme externes).
SAFE_HREF_RE = re.compile(r"^(https?://|mailto:)", re.IGNORECASE)
SITE_PATH_RE = re.compile(r"^/(?![/\\])")
# Médias : fichier envoyé par l'éditeur (uuid4 puis extension) ou URL https.
UPLOADED_MEDIA_RE = re.compile(r"^/api/staff/meetings/images/[0-9a-fA-F-]{36}\.[A-Za-z0-9]{1,8}$")
HTTPS_RE = re.compile(r"^https://", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Contenu BlockNote : nettoyage et texte
# ---------------------------------------------------------------------------

def _has_control(value: str) -> bool:
    return any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)


def _scalar(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _flat(raw: dict) -> dict:
    """Valeurs simples d'un objet (les objets et listes imbriqués sont retirés)."""
    return {key: value for key, value in raw.items() if isinstance(key, str) and _scalar(value)}


def safe_href(value: Any) -> str | None:
    """Lien accepté (sans espaces de bord) ou None s'il doit être retiré."""
    if not isinstance(value, str):
        return None
    href = value.strip()
    if not href or _has_control(href):
        return None
    return href if SAFE_HREF_RE.match(href) or SITE_PATH_RE.match(href) else None


def safe_media_url(value: Any) -> str:
    """URL de média acceptée, sinon chaîne vide."""
    if not isinstance(value, str):
        return ""
    url = value.strip()
    if not url or _has_control(url):
        return ""
    return url if UPLOADED_MEDIA_RE.fullmatch(url) or HTTPS_RE.match(url) else ""


def _text_item(text: str) -> dict:
    return {"type": "text", "text": text, "styles": {}}


def _clean_text_item(item: dict) -> dict:
    clean = _flat(item)
    clean["type"] = "text"
    styles = item.get("styles")
    clean["styles"] = _flat(styles) if isinstance(styles, dict) else {}
    return clean


def _text_items(content: Any) -> list:
    """Contenu d'un lien : texte seulement (chaînes et éléments `text`)."""
    if isinstance(content, str):
        return [_text_item(content)] if content else []
    items = []
    for item in content if isinstance(content, list) else []:
        if isinstance(item, str):
            if item:
                items.append(_text_item(item))
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            items.append(_clean_text_item(item))
    return items


def _clean_inline(content: list) -> list:
    clean = []
    for item in content:
        if isinstance(item, str):
            clean.append(item)
        elif not isinstance(item, dict):
            continue
        elif item.get("type") == "link":
            inner = _text_items(item.get("content"))
            href = safe_href(item.get("href"))
            if href is None:
                clean.extend(inner)
            else:
                clean.append({**_flat(item), "type": "link", "href": href, "content": inner})
        elif item.get("type") == "text":
            if isinstance(item.get("text"), str):
                clean.append(_clean_text_item(item))
        elif isinstance(item.get("text"), str):
            # Contenu en ligne inconnu : gardé comme simple texte.
            clean.append(_text_item(item["text"]))
        else:
            clean.extend(_text_items(item.get("content")))
    return clean


def _number_or_none(value: Any) -> Any:
    if value is None or (isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)):
        return value
    return None


def _clean_cell(cell: Any) -> Any:
    if isinstance(cell, str):
        return cell
    if isinstance(cell, list):
        return _clean_inline(cell)
    if isinstance(cell, dict):
        clean = _flat(cell)
        if isinstance(cell.get("props"), dict):
            clean["props"] = _flat(cell["props"])
        content = cell.get("content")
        clean["content"] = content if isinstance(content, str) else _clean_inline(content) if isinstance(content, list) else []
        return clean
    # Cellule illisible : vide, pour garder la forme du tableau.
    return []


def _clean_table(table: dict) -> dict:
    clean = _flat(table)
    clean["type"] = "tableContent"
    widths = table.get("columnWidths")
    if isinstance(widths, list):
        clean["columnWidths"] = [_number_or_none(width) for width in widths]
    rows = table.get("rows")
    clean["rows"] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        cells = row.get("cells")
        clean["rows"].append({**_flat(row), "cells": [_clean_cell(cell) for cell in cells] if isinstance(cells, list) else []})
    return clean


def _clean_block_content(content: Any) -> Any:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return _clean_inline(content)
    if isinstance(content, dict) and content.get("type") == "tableContent":
        return _clean_table(content)
    return []


def _clean_blocks(blocks: list, depth: int) -> list:
    clean = []
    for block in blocks:
        if not isinstance(block, dict) or not isinstance(block.get("type"), str) or not block["type"]:
            continue
        item = _flat(block)
        if "id" in item and not isinstance(item["id"], str):
            del item["id"]
        props = block.get("props")
        if isinstance(props, dict):
            item["props"] = _flat(props)
            if "url" in item["props"]:
                item["props"]["url"] = safe_media_url(item["props"]["url"])
        if "content" in block:
            item["content"] = _clean_block_content(block["content"])
        if "children" in block:
            children = block["children"]
            item["children"] = _clean_blocks(children, depth + 1) if depth < MAX_DEPTH and isinstance(children, list) else []
        clean.append(item)
    return clean


def sanitize_blocknote(blocks: Any) -> list:
    """Copie nettoyée d'une liste de blocs BlockNote.

    Tout élément qui n'est pas un objet est retiré (sauf une chaîne dans un contenu en ligne, lue comme du
    texte) ; liens limités au web, au courriel et aux chemins du site (sinon remplacés par leur
    texte) ; `props.url` des médias limité aux fichiers envoyés et à https ; enfants coupés au-delà de 20
    niveaux ; objets et listes inattendus retirés des propriétés.
    """
    return _clean_blocks(blocks, 1) if isinstance(blocks, list) else []


def _inline_text(content: Any, depth: int = 0) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list) or depth > MAX_DEPTH:
        return ""
    parts = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            if item.get("type") == "link":
                parts.append(_inline_text(item.get("content"), depth + 1))
            elif isinstance(item.get("text"), str):
                parts.append(item["text"])
    return "".join(parts)


def _collect_lines(blocks: Any, lines: list[str], depth: int, budget: list[int]) -> None:
    if not isinstance(blocks, list) or depth > MAX_DEPTH or budget[0] <= 0:
        return
    for block in blocks:
        if not isinstance(block, dict):
            continue
        content = block.get("content")
        texts = []
        if isinstance(content, dict):
            if content.get("type") == "tableContent":
                rows = content.get("rows")
                for row in rows if isinstance(rows, list) else []:
                    cells = row.get("cells") if isinstance(row, dict) else None
                    for cell in cells if isinstance(cells, list) else []:
                        texts.append(_inline_text(cell.get("content") if isinstance(cell, dict) else cell))
        else:
            texts.append(_inline_text(content))
        for text in texts:
            if text.strip():
                lines.append(text)
                budget[0] -= len(text) + 1
        if budget[0] <= 0:
            return
        _collect_lines(block.get("children"), lines, depth + 1, budget)


def blocks_to_text(blocks: Any) -> str:
    """Texte brut des blocs : texte en ligne, liens et cellules de tableau, une ligne chacun (100 000 max)."""
    lines: list[str] = []
    _collect_lines(blocks, lines, 1, [CONTENT_TEXT_MAX])
    return "\n".join(lines)[:CONTENT_TEXT_MAX]


def count_words(text: Any) -> int:
    return sum(1 for _ in WORD_RE.finditer(text)) if isinstance(text, str) else 0


def make_excerpt(text: Any) -> str:
    """Début du texte, espaces réduits, 220 caractères au plus (« … » s'il est coupé)."""
    if not isinstance(text, str):
        return ""
    words, length = [], 0
    for match in WORD_RE.finditer(text):
        length += len(match.group()) + (1 if words else 0)
        words.append(match.group())
        if length > EXCERPT_MAX:
            break
    flat = " ".join(words)
    if length <= EXCERPT_MAX:
        return flat
    return flat[:EXCERPT_MAX - 1].rstrip() + "…"


def _reject_constant(name: str):
    raise ValueError(f"Valeur JSON non standard : {name}")


def _utf8_safe(text: str) -> str:
    # Une moitié de paire de substitution (« \ud800 » en JSON) ne peut pas être enregistrée en BSON.
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return text.encode("utf-8", "replace").decode("utf-8")
    return text


def _parse_content(raw: Any) -> tuple[str, list | None]:
    """("empty" | "blocknote" | "text" | "unreadable", blocs nettoyés pour "blocknote")."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return "empty", None
    if not isinstance(raw, str):
        return "unreadable", None
    try:
        parsed = json.loads(raw, parse_constant=_reject_constant)
    except RecursionError:
        return "unreadable", None
    except ValueError:
        return "text", None
    if not isinstance(parsed, list):
        return "text", None
    try:
        blocks = sanitize_blocknote(parsed)
    except RecursionError:
        return "unreadable", None
    return ("blocknote", blocks) if blocks else ("empty", None)


def _dump_blocks(blocks: list) -> str:
    return _utf8_safe(json.dumps(blocks, ensure_ascii=False, separators=(",", ":")))


def prepare_content(raw: Any, *, allow_text: bool) -> tuple[str, str, int]:
    """(contenu à enregistrer, texte brut, nombre de mots).

    JSON BlockNote (liste) : nettoyé puis resérialisé ; une liste vide après nettoyage donne "". Autre
    contenu : texte brut accepté seulement avec `allow_text` (ancien PUT), sinon 422 « Contenu illisible. »
    (y compris un JSON trop imbriqué : jamais de 500).
    """
    try:
        kind, blocks = _parse_content(raw)
        if kind == "empty":
            return "", "", 0
        if kind == "blocknote":
            text = _utf8_safe(blocks_to_text(blocks))
            return _dump_blocks(blocks), text, count_words(text)
    except (RecursionError, ValueError, TypeError) as exc:
        raise unprocessable(MSG_UNREADABLE) from exc
    if not allow_text or not isinstance(raw, str):
        raise unprocessable(MSG_UNREADABLE)
    raw = _utf8_safe(raw)
    text = raw[:CONTENT_TEXT_MAX]
    return raw, text, count_words(text)


def content_text_of(raw: Any) -> str:
    """Texte brut d'un contenu stocké ; contenu illisible (trop imbriqué, type inattendu) = "". Ne lève pas."""
    try:
        kind, blocks = _parse_content(raw)
        if kind == "blocknote":
            return _utf8_safe(blocks_to_text(blocks))
    except (RecursionError, ValueError, TypeError):
        return ""
    if kind == "text":
        return _utf8_safe(raw[:CONTENT_TEXT_MAX])
    return ""


def read_content(raw: Any) -> tuple[str, str]:
    """(contenu à renvoyer, `content_format`) : JSON BlockNote nettoyé, ancien texte tel quel, ou vide."""
    try:
        kind, blocks = _parse_content(raw)
        if kind == "blocknote":
            return _dump_blocks(blocks), "blocknote"
    except (RecursionError, ValueError, TypeError):
        kind = "unreadable"
    if isinstance(raw, str) and raw.strip() and kind in ("text", "unreadable"):
        return raw, "text"
    return "", "empty"


def normalize_search(text: Any) -> str:
    """Minuscules, sans accents (NFD sans les marques), espaces réduits."""
    if not isinstance(text, str) or not text:
        return ""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return " ".join("".join(char for char in decomposed if unicodedata.category(char) != "Mn").split())


# ---------------------------------------------------------------------------
# Lecture tolérante
# ---------------------------------------------------------------------------

def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _valid_time(value: Any) -> str | None:
    return value if agenda_time.is_time_str(value) else None


def _valid_date(value: Any) -> str | None:
    return value if agenda_time.is_date_str(value) else None


def _item_id(raw: Any, prefix: str, index: int, seen: set) -> str:
    item_id = raw if is_valid_id(raw) and raw not in seen else f"{prefix}-{index}"
    while item_id in seen:
        item_id = str(uuid4())
    seen.add(item_id)
    return item_id


def legacy_agenda_items(agenda: Any) -> list[dict]:
    """Ordre du jour d'un ancien document : une ligne par point, puces retirées, id `legacy-0`, `legacy-1`…"""
    if not isinstance(agenda, str):
        return []
    titles = (LEGACY_BULLET.sub("", line, count=1).strip() for line in agenda.splitlines())
    titles = [title[:AGENDA_TITLE_MAX] for title in titles if title][:LIST_ITEMS_MAX]
    return [{"id": f"legacy-{index}", "title": title, "done": False} for index, title in enumerate(titles)]


def agenda_items_of(doc: dict) -> list[dict]:
    """`agenda_items` lisibles, sinon découpage de l'ancien texte `agenda`."""
    items, seen = [], set()
    raw_items = doc.get("agenda_items")
    for index, raw in enumerate(raw_items if isinstance(raw_items, list) else []):
        if not isinstance(raw, dict) or not isinstance(raw.get("title"), str) or not raw["title"].strip():
            continue
        items.append({
            "id": _item_id(raw.get("id"), "item", index, seen),
            "title": raw["title"].strip(),
            "done": raw.get("done") is True,
        })
    return items or legacy_agenda_items(doc.get("agenda"))


def agenda_text(items: Any) -> str:
    """Texte `agenda` des anciens lecteurs : « 1. …\\n2. … » (4000 caractères au plus, points entiers)."""
    lines, total = [], 0
    for item in items or []:
        title = item.get("title") if isinstance(item, dict) else getattr(item, "title", None)
        if not isinstance(title, str) or not title.strip():
            continue
        line = f"{len(lines) + 1}. {title.strip()}"
        added = len(line) + (1 if lines else 0)
        if total + added > AGENDA_TEXT_MAX:
            break
        lines.append(line)
        total += added
    return "\n".join(lines)


def _decisions_of(doc: dict) -> list[dict]:
    decisions, seen = [], set()
    raw_list = doc.get("decisions")
    for index, raw in enumerate(raw_list if isinstance(raw_list, list) else []):
        if isinstance(raw, dict) and isinstance(raw.get("text"), str) and raw["text"].strip():
            decisions.append({"id": _item_id(raw.get("id"), "decision", index, seen), "text": raw["text"].strip()})
    return decisions


def _action_out(raw: dict, item_id: str) -> dict:
    return {
        "id": item_id,
        "text": raw["text"].strip(),
        "assignee": identity(raw.get("assignee")),
        "due_date": _valid_date(raw.get("due_date")),
        "done": raw.get("done") is True,
        "done_at": iso_z_or_none(raw.get("done_at")),
        "done_by": identity(raw.get("done_by")),
    }


def _actions_of(doc: dict) -> list[dict]:
    actions, seen = [], set()
    raw_list = doc.get("action_items")
    for index, raw in enumerate(raw_list if isinstance(raw_list, list) else []):
        if isinstance(raw, dict) and isinstance(raw.get("text"), str) and raw["text"].strip():
            actions.append(_action_out(raw, _item_id(raw.get("id"), "action", index, seen)))
    return actions


def _participants_of(doc: dict) -> list[dict]:
    participants, seen = [], set()
    raw_list = doc.get("participants")
    for raw in raw_list if isinstance(raw_list, list) else []:
        person = identity(raw)
        if not person or person["id"] in seen:
            continue
        seen.add(person["id"])
        attendance = raw.get("attendance") if isinstance(raw, dict) else None
        participants.append({**person, "attendance": attendance if attendance in ATTENDANCES else "invite"})
    return participants


def _status(doc: dict) -> str:
    stored = doc.get("status")
    if stored in (STATUS_WRITTEN, STATUS_PENDING):
        return stored
    content = doc.get("content_markdown")
    if isinstance(content, str):
        return STATUS_WRITTEN if content.strip() else STATUS_PENDING
    return STATUS_WRITTEN if _int(doc.get("word_count")) else STATUS_PENDING


def _base_fields(doc: dict) -> dict:
    start_time = _valid_time(doc.get("start_time"))
    return {
        "id": str(doc.get("id") or ""),
        "title": _text(doc.get("title")),
        "meeting_date": _text(doc.get("meeting_date")),
        "start_time": start_time,
        "end_time": _valid_time(doc.get("end_time")) if start_time else None,
        "location": _text(doc.get("location")),
        "status": _status(doc),
        "is_locked": doc.get("is_locked") is True,
        "cancelled": doc.get("cancelled") is True,
        "cancel_reason": _text(doc.get("cancel_reason")),
        "author": identity(doc.get("author")),
        "participants": _participants_of(doc),
        "agenda": _text(doc.get("agenda")),
        "agenda_items": agenda_items_of(doc),
        "decisions": _decisions_of(doc),
        "action_items": _actions_of(doc),
        "reminders": stored_reminders(doc.get("reminders")),
        "revision": _int(doc.get("revision")),
        "word_count": _int(doc.get("word_count")),
        "excerpt": _text(doc.get("excerpt"))[:EXCERPT_MAX],
        "created_at": iso_or_none(doc.get("created_at")),
        "updated_at": iso_or_none(doc.get("updated_at")),
        "updated_by": identity(doc.get("updated_by")),
        "locked_by": identity(doc.get("locked_by")),
        "locked_at": iso_z_or_none(doc.get("locked_at")),
    }


def normalize_meeting(doc: dict) -> dict:
    """Réunion complète lue avec tolérance (anciens documents compris), sans rien écrire.

    Ajoute `content_markdown` (JSON BlockNote nettoyé, ancien texte tel quel, ou "") et `content_format`
    (`empty` | `blocknote` | `text`) quand le document porte son contenu.
    """
    meeting = _base_fields(doc)
    content, content_format = read_content(doc.get("content_markdown"))
    meeting["content_markdown"] = content
    meeting["content_format"] = content_format
    return meeting


def _paris_now(now: Any = None) -> datetime:
    moment = agenda_time.as_utc(now) if now is not None else agenda_time.now_utc()
    return moment.astimezone(agenda_time.PARIS)


def _phase_at(doc: dict, local: datetime) -> str:
    if doc.get("cancelled") is True:
        return "annulee"
    today = local.date().isoformat()
    meeting_date = _text(doc.get("meeting_date"))
    start_time = _valid_time(doc.get("start_time"))
    if meeting_date > today or (
        meeting_date == today and (start_time is None or start_time > local.strftime("%H:%M"))
    ):
        return "a_venir"
    return "redige" if _status(doc) == STATUS_WRITTEN else "a_rediger"


def phase(doc: dict, now: Any = None) -> str:
    """`annulee`, `a_venir`, `a_rediger` ou `redige` (calculée, jamais stockée) ; now = maintenant par défaut."""
    return _phase_at(doc, _paris_now(now))


def _summary_from(meeting: dict, viewer: Any, local: datetime) -> dict:
    viewer_id, is_responsable = viewer_info(viewer)
    participant_ids = [person["id"] for person in meeting["participants"]]
    items = meeting["agenda_items"]
    actions = meeting["action_items"]
    return {
        "id": meeting["id"],
        "title": meeting["title"],
        "meeting_date": meeting["meeting_date"],
        "start_time": meeting["start_time"],
        "end_time": meeting["end_time"],
        "location": meeting["location"],
        "phase": _phase_at(meeting, local),
        "status": meeting["status"],
        "is_locked": meeting["is_locked"],
        "cancelled": meeting["cancelled"],
        "author": meeting["author"],
        "participants_count": len(participant_ids),
        "participant_ids": participant_ids,
        "is_participant": bool(viewer_id) and viewer_id in participant_ids,
        "agenda_preview": [item["title"] for item in items[:AGENDA_PREVIEW_MAX]],
        "agenda_count": len(items),
        "agenda_done_count": sum(1 for item in items if item["done"]),
        "decisions_count": len(meeting["decisions"]),
        "actions_count": len(actions),
        "open_actions_count": sum(1 for action in actions if not action["done"]),
        "word_count": meeting["word_count"],
        "excerpt": meeting["excerpt"],
        "updated_at": meeting["updated_at"],
        "can_manage": is_responsable,
    }


def to_summary(doc: dict, viewer: Any, now: Any = None) -> dict:
    """Réunion au format `MeetingSummaryOut` (ne lit jamais le contenu)."""
    return _summary_from(_base_fields(doc), viewer, _paris_now(now))


def to_detail(
    doc: dict,
    viewer: Any,
    schedule: Any = None,
    participants_absent: Any = None,
    now: Any = None,
) -> dict:
    """Réunion au format `MeetingDetailOut`.

    `schedule` = lignes de la file des rappels de la date en cours ; `participants_absent` = id des
    participants absents ce jour-là (calculés par l'appelant).
    """
    meeting = normalize_meeting(doc)
    ids = {person["id"] for person in meeting["participants"]}
    absent = [str(person_id) for person_id in participants_absent or [] if str(person_id) in ids]
    return {
        **_summary_from(meeting, viewer, _paris_now(now)),
        "agenda": meeting["agenda"],
        "agenda_items": meeting["agenda_items"],
        "content_markdown": meeting["content_markdown"],
        "content_format": meeting["content_format"],
        "decisions": meeting["decisions"],
        "action_items": meeting["action_items"],
        "participants": meeting["participants"],
        "participants_absent": list(dict.fromkeys(absent)),
        "reminders": reminder_info(doc.get("reminders"), schedule),
        "revision": meeting["revision"],
        "created_at": meeting["created_at"],
        "updated_by": meeting["updated_by"],
        "locked_by": meeting["locked_by"],
        "locked_at": meeting["locked_at"],
        "cancel_reason": meeting["cancel_reason"],
        "can_edit": not meeting["is_locked"],
        "viewer": viewer_out(viewer),
    }


# ---------------------------------------------------------------------------
# Champs dérivés (recherche, extrait, nombre de mots)
# ---------------------------------------------------------------------------

def build_search_text(doc: dict) -> str:
    """Titre, lieu, ordre du jour, décisions, actions et `content_text`, normalisés (20 000 caractères)."""
    parts = [
        _text(doc.get("title")),
        _text(doc.get("location")),
        *(item["title"] for item in agenda_items_of(doc)),
        *(decision["text"] for decision in _decisions_of(doc)),
        *(action["text"] for action in _actions_of(doc)),
        _text(doc.get("content_text")),
    ]
    joined = "\n".join(part for part in parts if part.strip())
    return normalize_search(joined[:SEARCH_TEXT_MAX * 4])[:SEARCH_TEXT_MAX]


def _derived_from_text(doc: dict, content_text: str) -> dict:
    return {
        "content_text": content_text,
        "search_text": build_search_text({**doc, "content_text": content_text}),
        "word_count": count_words(content_text),
        "excerpt": make_excerpt(content_text),
    }


def derived_fields(doc: dict) -> dict:
    """`content_text`, `search_text`, `word_count` et `excerpt` d'une réunion. Ne lève jamais.

    Contenu illisible (JSON trop imbriqué, type inattendu) : texte vide, recherche sur le reste.
    """
    return _derived_from_text(doc, content_text_of(doc.get("content_markdown")))


# ---------------------------------------------------------------------------
# Écritures
# ---------------------------------------------------------------------------

async def get(meeting_id: str) -> dict:
    """Document complet (sans `_id`) ; 404 « Réunion introuvable. » si l'id est invalide ou inconnu."""
    if not is_valid_id(meeting_id):
        raise not_found(NOT_FOUND)
    doc = await db.meeting_summaries.find_one({"id": meeting_id}, {"_id": 0})
    if not doc:
        raise not_found(NOT_FOUND)
    return doc


def _as_dict(item: Any) -> dict:
    return item.model_dump() if isinstance(item, BaseModel) else dict(item)


def _input_id(raw: Any, seen: set) -> str:
    """Id envoyé par le client s'il est valide et pas déjà pris dans la liste, sinon un uuid."""
    item_id = raw if is_valid_id(raw) and raw not in seen else str(uuid4())
    seen.add(item_id)
    return item_id


def _agenda_items_in(items: Any) -> list[dict]:
    clean, seen = [], set()
    for item in items or []:
        data = _as_dict(item)
        clean.append({
            "id": _input_id(data.get("id"), seen),
            "title": str(data["title"]).strip()[:AGENDA_TITLE_MAX],
            "done": data.get("done") is True,
        })
    return clean


def _decisions_in(items: Any) -> list[dict]:
    clean, seen = [], set()
    for item in items or []:
        data = _as_dict(item)
        clean.append({"id": _input_id(data.get("id"), seen), "text": str(data["text"]).strip()})
    return clean


def _check_times(start_time: str | None, end_time: str | None) -> None:
    if end_time and not start_time:
        raise unprocessable(MSG_START_TIME_REQUIRED)
    if start_time and end_time and end_time <= start_time:
        raise unprocessable(MSG_END_TIME_ORDER)


def _check_date(meeting_date: str) -> None:
    if not agenda_time.date_in_bounds(meeting_date, past_days=PAST_DAYS, future_days=FUTURE_DAYS):
        raise unprocessable(MSG_OUT_OF_BOUNDS)


async def create(payload: MeetingCreateIn | dict, helper, viewer: Any = None) -> dict:
    """Crée une réunion (contenu vide, rappels par défaut) et renvoie le document stocké.

    L'appelant synchronise ensuite les rappels. 422 heure, date ou participant ; 503 annuaire.
    """
    model = payload if isinstance(payload, MeetingCreateIn) else MeetingCreateIn.model_validate(payload)
    reminders = reminders_from_input(model.reminders)
    if viewer is not None and reminders["ping_role"] and not viewer_info(viewer)[1]:
        raise forbidden(PING_FORBIDDEN)
    _check_times(model.start_time, model.end_time)
    _check_date(model.meeting_date)
    people = await agenda_people.resolve_people(model.participant_ids, {}) if model.participant_ids else []
    items = _agenda_items_in(model.agenda_items)
    me = session_identity(helper)
    now = agenda_time.now_iso()
    doc = {
        "id": str(uuid4()),
        "title": model.title,
        "agenda": agenda_text(items),
        "agenda_items": items,
        "content_markdown": "",
        "status": STATUS_PENDING,
        "meeting_date": model.meeting_date,
        "start_time": model.start_time,
        "end_time": model.end_time if model.start_time else None,
        "location": model.location,
        "participants": [{**person, "attendance": "invite"} for person in people],
        "decisions": [],
        "action_items": [],
        "cancelled": False,
        "cancel_reason": "",
        "reminders": reminders,
        "revision": 0,
        "author": me,
        "created_at": now,
        "updated_at": now,
        "updated_by": me,
        "is_locked": False,
        "locked_by": None,
        "locked_at": None,
    }
    doc.update(_derived_from_text(doc, ""))
    await db.meeting_summaries.insert_one(dict(doc))
    return doc


def conflict_response(current: dict) -> JSONResponse:
    """409 de révision : `{detail, code, current_revision, updated_at, updated_by}` (pas une HTTPException)."""
    body = RevisionConflictOut(
        detail=CONFLICT_MESSAGE,
        current_revision=_int(current.get("revision")),
        updated_at=iso_or_none(current.get("updated_at")),
        updated_by=identity(current.get("updated_by")),
    )
    return JSONResponse(status_code=409, content=body.model_dump(mode="json"))


def _schedule_updates(existing: dict, fields: dict) -> dict:
    """Date et heures fusionnées (`start_time: null` efface aussi la fin non envoyée)."""
    updates: dict[str, Any] = {}
    if not {"meeting_date", "start_time", "end_time"} & fields.keys():
        return updates
    start_time = fields["start_time"] if "start_time" in fields else _valid_time(existing.get("start_time"))
    if "end_time" in fields:
        end_time = fields["end_time"]
    elif start_time is None:
        end_time = None
    else:
        end_time = _valid_time(existing.get("end_time"))
    if "start_time" in fields or "end_time" in fields:
        _check_times(start_time, end_time)
        updates["start_time"] = start_time
        updates["end_time"] = end_time
    if "meeting_date" in fields:
        _check_date(fields["meeting_date"])
        updates["meeting_date"] = fields["meeting_date"]
    return updates


async def _actions_in(existing: dict, items: list, known: dict, me: dict, now_z: str) -> list[dict]:
    """Nouvelle liste `action_items` : pour une action existante, un champ absent garde la valeur stockée."""
    stored: dict[str, dict] = {}
    for raw in existing.get("action_items") or []:
        if isinstance(raw, dict) and is_valid_id(raw.get("id")):
            stored.setdefault(raw["id"], raw)
    wanted = [
        item.assignee_id for item in items
        if "assignee_id" in item.model_fields_set and item.assignee_id
    ]
    people = {person["id"]: person for person in await agenda_people.resolve_people(wanted, known)} if wanted else {}

    actions, seen = [], set()
    for item in items:
        sent = item.model_fields_set
        item_id = _input_id(item.id, seen)
        previous = stored.get(item_id)
        if "assignee_id" in sent:
            assignee = people.get(item.assignee_id) if item.assignee_id else None
        else:
            assignee = identity(previous.get("assignee")) if previous else None
        due_date = item.due_date if "due_date" in sent else (_valid_date(previous.get("due_date")) if previous else None)
        was_done = previous is not None and previous.get("done") is True
        if previous is not None and ("done" not in sent or item.done is None or item.done is was_done):
            done, done_at, done_by = was_done, previous.get("done_at"), identity(previous.get("done_by"))
        else:
            done = item.done is True
            done_at, done_by = (now_z, me) if done else (None, None)
        actions.append({
            "id": item_id,
            "text": item.text,
            "assignee": assignee,
            "due_date": due_date,
            "done": done,
            "done_at": done_at if done else None,
            "done_by": done_by if done else None,
        })
    return actions


async def patch(meeting_id: str, payload: MeetingPatch | dict, helper, viewer: Any) -> dict | JSONResponse:
    """Écrit le compte-rendu ou les informations d'une réunion ; renvoie le document à jour.

    Filtre atomique de révision et de verrouillage ; si l'écriture ne passe pas : 404 (supprimée),
    403 « Ce résumé est verrouillé. » ou `JSONResponse` 409 (`conflict_response`), renvoyée et non levée.
    Champs réservés aux responsables : 403. L'appelant synchronise les rappels si `SCHEDULE_FIELDS` est touché.
    """
    model = payload if isinstance(payload, MeetingPatch) else MeetingPatch.model_validate(payload)
    fields = model.model_dump(exclude_unset=True)
    message = null_required_message(fields) or (None if "expected_revision" in fields else "Champ obligatoire : révision.")
    if message:
        raise unprocessable(message)
    expected = fields["expected_revision"]
    _, is_responsable = viewer_info(viewer)
    if RESERVED_FIELDS & fields.keys() and not is_responsable:
        raise forbidden(RESERVED_FORBIDDEN)
    existing = await get(meeting_id)
    if existing.get("is_locked") is True:
        raise forbidden(LOCKED)
    if _int(existing.get("revision")) != expected:
        return conflict_response(existing)

    me = session_identity(helper)
    known = agenda_people.known_identities(existing)
    updates: dict[str, Any] = {}
    content_text: str | None = None

    if "title" in fields:
        updates["title"] = fields["title"]
    if "content_markdown" in fields:
        updates["content_markdown"], content_text, _words = prepare_content(fields["content_markdown"], allow_text=False)
    if "agenda_items" in fields:
        updates["agenda_items"] = _agenda_items_in(model.agenda_items)
        updates["agenda"] = agenda_text(updates["agenda_items"])
    if "decisions" in fields:
        updates["decisions"] = _decisions_in(model.decisions)
    updates.update(_schedule_updates(existing, fields))
    if "location" in fields:
        updates["location"] = fields["location"]
    if "cancelled" in fields:
        updates["cancelled"] = fields["cancelled"]
        if not fields["cancelled"] and "cancel_reason" not in fields:
            updates["cancel_reason"] = ""
    if "cancel_reason" in fields:
        updates["cancel_reason"] = fields["cancel_reason"]
    if "reminders" in fields:
        updates["reminders"] = merge_reminders(existing.get("reminders"), model.reminders)

    participants = _participants_of(existing)
    if "participant_ids" in fields:
        attendance = {person["id"]: person["attendance"] for person in participants}
        people = await agenda_people.resolve_people(fields["participant_ids"], known)
        participants = [{**person, "attendance": attendance.get(person["id"], "invite")} for person in people]
        updates["participants"] = participants
    if fields.get("attendance"):
        present_ids = {person["id"] for person in participants}
        for person_id in fields["attendance"]:
            if person_id not in present_ids:
                raise unprocessable(f"Participant inconnu : {person_id[:64]}.")
        updates["participants"] = [
            {**person, "attendance": fields["attendance"].get(person["id"], person["attendance"])}
            for person in participants
        ]
    if "action_items" in fields:
        now_z = agenda_time.iso_z(agenda_time.now_utc())
        updates["action_items"] = await _actions_in(existing, model.action_items, known, me, now_z)

    merged = {**existing, **updates}
    content = merged.get("content_markdown")
    updates["status"] = STATUS_WRITTEN if isinstance(content, str) and content.strip() else STATUS_PENDING
    if content_text is None:
        stored_text = existing.get("content_text")
        content_text = stored_text if isinstance(stored_text, str) else content_text_of(content)
    updates.update(_derived_from_text(merged, content_text))
    updates["updated_at"] = agenda_time.now_iso()
    updates["updated_by"] = me
    updates["revision"] = expected + 1

    query: dict[str, Any] = {"id": meeting_id, "is_locked": {"$ne": True}}
    if expected == 0:
        query["$or"] = [{"revision": 0}, {"revision": None}, {"revision": {"$exists": False}}]
    else:
        query["revision"] = expected
    result = await db.meeting_summaries.update_one(query, {"$set": updates})
    if result.matched_count == 0:
        current = await db.meeting_summaries.find_one(
            {"id": meeting_id}, {"_id": 0, "is_locked": 1, "revision": 1, "updated_at": 1, "updated_by": 1},
        )
        if not current:
            raise not_found(NOT_FOUND)
        if current.get("is_locked") is True:
            raise forbidden(LOCKED)
        return conflict_response(current)
    for action in updates.get("action_items") or []:
        who = (action.get("assignee") or {}).get("id")
        before = next((a for a in existing.get("action_items") or [] if isinstance(a, dict) and a.get("id") == action["id"]), None)
        if who and who != helper.id and not action.get("done") and who != ((before or {}).get("assignee") or {}).get("id"):
            await create_notification(who, "action_assigned", "Action de réunion attribuée", action.get("text", ""), f"/staff/meetings/{meeting_id}")
    return {**existing, **updates}


async def toggle_action(meeting_id: str, action_id: str, done: bool, helper) -> dict:
    """Coche ou décoche une action (`ActionToggleOut`), même sur une réunion verrouillée, sans toucher `revision`."""
    if not is_valid_id(meeting_id):
        raise not_found(NOT_FOUND)
    if not is_valid_id(action_id):
        raise not_found(ACTION_NOT_FOUND)
    doc = await db.meeting_summaries.find_one(
        {"id": meeting_id}, {"_id": 0, "id": 1, "action_items": 1, "revision": 1},
    )
    if not doc:
        raise not_found(NOT_FOUND)
    raw = next(
        (item for item in doc.get("action_items") or [] if isinstance(item, dict) and item.get("id") == action_id),
        None,
    )
    if raw is None or not isinstance(raw.get("text"), str) or not raw["text"].strip():
        raise not_found(ACTION_NOT_FOUND)
    done = bool(done)
    if (raw.get("done") is True) != done:
        me = session_identity(helper)
        changes = {
            "done": done,
            "done_at": agenda_time.iso_z(agenda_time.now_utc()) if done else None,
            "done_by": me if done else None,
        }
        result = await db.meeting_summaries.update_one(
            {"id": meeting_id, "action_items.id": action_id},
            {"$set": {
                **{f"action_items.$.{key}": value for key, value in changes.items()},
                "updated_at": agenda_time.now_iso(),
                "updated_by": me,
            }},
        )
        if result.matched_count == 0:
            if not await db.meeting_summaries.find_one({"id": meeting_id}, {"_id": 0, "id": 1}):
                raise not_found(NOT_FOUND)
            raise not_found(ACTION_NOT_FOUND)
        raw = {**raw, **changes}
    return {"meeting_id": meeting_id, "revision": _int(doc.get("revision")), "item": _action_out(raw, action_id)}


async def set_lock(meeting_id: str, locked: bool, helper) -> dict:
    """Verrouille ou déverrouille (idempotent), sans toucher `revision`. Renvoie le document à jour."""
    doc = await get(meeting_id)
    locked = bool(locked)
    if (doc.get("is_locked") is True) == locked:
        return doc
    changes = {
        "is_locked": locked,
        "locked_by": session_identity(helper) if locked else None,
        "locked_at": agenda_time.now_iso() if locked else None,
    }
    result = await db.meeting_summaries.update_one({"id": meeting_id}, {"$set": changes})
    if result.matched_count == 0:
        raise not_found(NOT_FOUND)
    return {**doc, **changes}


async def delete(meeting_id: str, helper=None, viewer: Any = None) -> None:
    """Supprime une réunion non verrouillée (403 sinon). L'appelant annule ensuite ses rappels."""
    if not is_valid_id(meeting_id):
        raise not_found(NOT_FOUND)
    doc = await db.meeting_summaries.find_one({"id": meeting_id}, {"_id": 0, "id": 1, "is_locked": 1})
    if not doc:
        raise not_found(NOT_FOUND)
    if doc.get("is_locked") is True:
        raise forbidden(LOCKED)
    result = await db.meeting_summaries.delete_one({"id": meeting_id, "is_locked": {"$ne": True}})
    if result.deleted_count == 0:
        if await db.meeting_summaries.find_one({"id": meeting_id}, {"_id": 0, "id": 1}):
            raise forbidden(LOCKED)
        raise not_found(NOT_FOUND)


# ---------------------------------------------------------------------------
# Listes : liste filtrée et vue d'ensemble
# ---------------------------------------------------------------------------

def _when(doc: dict) -> tuple[str, str]:
    return _text(doc.get("meeting_date")), _valid_time(doc.get("start_time")) or ""


async def _summary_docs(query: dict) -> list[dict]:
    # Les plus récentes d'abord : au-delà de SCAN_LIMIT, ce sont les plus anciennes qui manquent.
    cursor = db.meeting_summaries.find(query, MEETING_SUMMARY_PROJECTION).sort("meeting_date", -1)
    return await cursor.to_list(SCAN_LIMIT)


async def list_meetings(
    q: str | None = None,
    phase: str | None = None,  # noqa: A002 - nom du paramètre de l'API
    limit: int = 50,
    offset: int = 0,
    now: Any = None,
) -> dict:
    """`{"items": [documents projetés], "total", "counts"}` ; `counts` ne dépend que de `q`.

    Recherche insensible à la casse et aux accents dans `search_text` (`re.escape`). Tri croissant pour
    `a_venir`, décroissant sinon. Les documents ne contiennent jamais le contenu.
    """
    if phase and phase not in PHASES:
        raise unprocessable(MSG_INVALID_PHASE)
    limit = max(1, min(int(limit or 50), LIST_LIMIT_MAX))
    offset = max(0, int(offset or 0))
    needle = normalize_search(q or "")[:100]
    docs = await _summary_docs({"search_text": {"$regex": re.escape(needle)}} if needle else {})
    local = _paris_now(now)
    phased = [(doc, _phase_at(doc, local)) for doc in docs]
    counts = {"all": len(phased), **{name: 0 for name in PHASES}}
    for _doc, doc_phase in phased:
        counts[doc_phase] += 1
    selected = [doc for doc, doc_phase in phased if not phase or doc_phase == phase]
    selected.sort(key=_when, reverse=phase != "a_venir")
    return {"items": selected[offset:offset + limit], "total": len(selected), "counts": counts}


async def overview(viewer: Any, now: Any = None) -> dict:
    """Vue d'ensemble : prochaine réunion, comptes-rendus à rédiger, actions ouvertes et compteurs.

    `next_meeting` est un `MeetingSummaryOut` (avec `id`) : l'appelant relit le document complet pour
    construire le `MeetingDetailOut` (rappels, absents). Lecture avec `MEETING_SUMMARY_PROJECTION`.
    """
    viewer_id, _ = viewer_info(viewer)
    local = _paris_now(now)
    upcoming, to_write, open_actions = [], [], []
    for doc in await _summary_docs({}):
        doc_phase = _phase_at(doc, local)
        if doc_phase == "a_venir":
            upcoming.append(doc)
        elif doc_phase == "a_rediger":
            to_write.append(doc)
        if doc.get("cancelled") is True:
            continue
        for action in _actions_of(doc):
            if action["done"]:
                continue
            assignee = action["assignee"]
            open_actions.append({
                "meeting_id": str(doc.get("id") or ""),
                "meeting_title": _text(doc.get("title")),
                "meeting_date": _text(doc.get("meeting_date")),
                "is_mine": bool(assignee and viewer_id and assignee["id"] == viewer_id),
                "item": action,
            })
    upcoming.sort(key=_when)
    to_write.sort(key=_when, reverse=True)
    open_actions.sort(key=lambda ref: (
        not ref["is_mine"],
        ref["item"]["due_date"] is None,
        ref["item"]["due_date"] or "",
        ref["meeting_date"],
        ref["meeting_id"],
    ))
    return {
        "today": local.date().isoformat(),
        "viewer": viewer_out(viewer),
        "next_meeting": to_summary(upcoming[0], viewer, now) if upcoming else None,
        "to_write": [to_summary(doc, viewer, now) for doc in to_write[:TO_WRITE_MAX]],
        "open_actions": open_actions[:OPEN_ACTIONS_MAX],
        "counts": {
            "a_venir": len(upcoming),
            "a_rediger": len(to_write),
            "open_actions": len(open_actions),
            "my_open_actions": sum(1 for ref in open_actions if ref["is_mine"]),
        },
    }
