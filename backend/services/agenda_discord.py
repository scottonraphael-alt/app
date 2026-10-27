"""Rappels de l'agenda : message Discord Components V2 et envoi par l'API REST (httpx).

Les cibles (`ReminderTarget`) et les réglages (`EffectiveSettings`) sont lus par attribut
ou par clé : un objet, une dataclass ou un dict conviennent.

Permissions du bot dans le salon des rappels : « Voir le salon » et « Envoyer des messages ».
Pour la mention, le rôle doit être mentionnable, ou le bot doit avoir « Mentionner @everyone,
@here et tous les rôles ».
"""
import math
import os
import re
import uuid
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

import config
from services import agenda_time
from services.discord_service import DISCORD_API_BASE, ensure_discord_id

IS_COMPONENTS_V2 = 1 << 15  # 32768
REQUEST_TIMEOUT = 10.0
USER_AGENT = "DiscordBot (https://iris.loasis.app, 1.0)"
DEFAULT_RETRY_AFTER = 5.0
DEFAULT_FRONTEND_URL = "https://iris.loasis.app"

MAX_TITLE = 160
MAX_TEXT_DISPLAY = 1000
MAX_TOTAL_TEXT = 3500
MAX_COMPONENTS = 12
MAX_NONCE = 25
MAX_ERROR = 300
MAX_BUTTON_URL = 512

REMINDABLE_KINDS = {"meeting", "entry"}
OFFSET_KEYS = ("J-7", "J-2", "J-1", "H-1")
# Midi à Paris et non minuit : <t:X:D> s'affiche dans le fuseau du lecteur, et minuit à Paris
# tombe la veille pour tout lecteur à l'ouest (Royaume-Uni, Québec, Antilles).
ALL_DAY_ANCHOR = "12:00"

# type -> (émoji d'en-tête, libellé par défaut, couleur d'accent)
TYPE_STYLES = {
    "reunion": ("🗓️", "Réunion", 0x49658D),
    "evenement": ("🎉", "Événement", 0x765094),
    "echeance": ("⏳", "Échéance", 0x954C50),
    "rappel": ("🔔", "Rappel", 0x88672E),
    "permanence": ("🎧", "Permanence", 0x4A675C),
    "autre": ("📌", "Autre", 0x64706A),
}
TEST_ACCENT = 0x88672E

_ROLE_ID = re.compile(r"[0-9]{17,20}")
_URL = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
_INLINE_SPECIAL = re.compile(r"([\\*_~`|<\[])")
_LINE_START_SPECIAL = re.compile(r"^([ \t]*)([#>\-])", re.MULTILINE)
_MASS_MENTION = re.compile(r"@(everyone|here)", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class DiscordSendError(Exception):
    def __init__(self, status: int | None = None, message: str = "") -> None:
        self.status = status
        self.message = (message or f"Erreur Discord ({status if status is not None else 'réseau'}).")[:MAX_ERROR]
        super().__init__(self.message)


class DiscordRateLimited(DiscordSendError):
    def __init__(self, retry_after: float = DEFAULT_RETRY_AFTER) -> None:
        self.retry_after = float(retry_after)
        super().__init__(429, f"Discord limite les envois : nouvel essai dans {self.retry_after:g} s.")


class DiscordTemporaryError(DiscordSendError):
    """5xx, délai dépassé ou erreur réseau : on pourra réessayer."""


class DiscordPermanentError(DiscordSendError):
    """4xx autre que 429 (permissions, salon inconnu…) : réessayer ne servirait à rien."""


def _get(source: Any, name: str, default: Any = None) -> Any:
    if source is None:
        return default
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _retry_after(response: httpx.Response) -> float:
    value: Any = None
    try:
        body = response.json()
        if isinstance(body, dict):
            value = body.get("retry_after")
    except ValueError:
        pass
    if value is None:
        value = response.headers.get("retry-after")
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return DEFAULT_RETRY_AFTER
    if not math.isfinite(seconds) or seconds < 0:
        return DEFAULT_RETRY_AFTER
    return min(seconds, 86400.0)


def _error_detail(response: httpx.Response) -> str:
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict) and body.get("message"):
            detail = str(body["message"])
            if body.get("code") is not None:
                detail += f" (code {body['code']})"
    except ValueError:
        pass
    if not detail:
        detail = " ".join(response.text.split())
    return f"HTTP {response.status_code} : {detail}"[:MAX_ERROR]


async def post_channel_message(channel_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Publie `payload` dans le salon. Renvoie le message créé (JSON Discord) ou lève une DiscordSendError."""
    try:
        channel_id = ensure_discord_id(channel_id)
    except HTTPException:
        raise DiscordPermanentError(None, "Envoi impossible : identifiant de salon Discord invalide.") from None

    token = config.DISCORD_BOT_TOKEN
    if not token:
        raise DiscordPermanentError(None, "Envoi impossible : DISCORD_BOT_TOKEN non défini.")

    headers = {"Authorization": f"Bot {token}", "User-Agent": USER_AGENT}
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.post(
                f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
                json=payload,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise DiscordTemporaryError(None, f"{type(exc).__name__} : {exc}") from exc

    status_code = response.status_code
    if status_code == 429:
        raise DiscordRateLimited(_retry_after(response))
    if status_code >= 500:
        raise DiscordTemporaryError(status_code, _error_detail(response))
    if status_code >= 400:
        raise DiscordPermanentError(status_code, _error_detail(response))
    if not 200 <= status_code < 300:
        raise DiscordTemporaryError(status_code, _error_detail(response))

    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _escape_plain(text: str) -> str:
    text = _INLINE_SPECIAL.sub(r"\\\1", text)
    return _MASS_MENTION.sub("@\u200b\\1", text)


def escape_markdown(text: Any, *, single_line: bool = False) -> str:
    """Neutralise la mise en forme Discord d'un texte saisi (les URL restent cliquables)."""
    text = "" if text is None else str(text)
    text = _CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    if single_line:
        text = " ".join(part.strip() for part in text.split("\n") if part.strip())

    parts: list[str] = []
    position = 0
    for match in _URL.finditer(text):
        parts.append(_escape_plain(text[position:match.start()]))
        parts.append(match.group(0))
        position = match.end()
    parts.append(_escape_plain(text[position:]))
    return _LINE_START_SPECIAL.sub(r"\1\\\2", "".join(parts))


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _clip_escaped(text: str, limit: int) -> str:
    """Coupe un texte déjà échappé sans laisser de barre oblique orpheline avant « … »."""
    if len(text) <= limit:
        return text
    cut = text[: max(0, limit - 1)].rstrip()
    trailing = len(cut) - len(cut.rstrip("\\"))
    if trailing % 2:
        cut = cut[:-1]
    return cut + "…"


def _unix(day: Any, hhmm: Any = None) -> int:
    """Secondes Unix d'une date et d'une heure murales de Paris (midi sans heure : ALL_DAY_ANCHOR)."""
    return int(agenda_time.local_start(day, hhmm or ALL_DAY_ANCHOR).timestamp())


def _event_unix(target: Any) -> int:
    try:
        event_at = agenda_time.as_utc(_get(target, "event_at"))
    except (TypeError, ValueError):
        event_at = None
    if event_at is None:
        raise ValueError("Date de l'élément illisible.")
    return int(event_at.timestamp())


def _when_text(target: Any) -> str:
    start_date = _get(target, "start_date")
    start_time = _get(target, "start_time") or None
    end_date = _get(target, "end_date") or None
    end_time = _get(target, "end_time") or None
    all_day = bool(_get(target, "all_day")) or not start_time
    if end_date == start_date:
        end_date = None

    try:
        if all_day:
            start = _unix(start_date)
            if end_date:
                return f"<t:{start}:D> → <t:{_unix(end_date)}:D>"
            return f"<t:{start}:D> (toute la journée)"

        start = _unix(start_date, start_time)
        text = f"<t:{start}:F>"
        if end_time:
            end_style = "f" if end_date else "t"
            text += f" → <t:{_unix(end_date or start_date, end_time)}:{end_style}>"
        elif end_date:
            text += f" → <t:{_unix(end_date)}:D>"
        return f"{text} · <t:{start}:R>"
    except (TypeError, ValueError):
        start = _event_unix(target)
        return f"<t:{start}:F> · <t:{start}:R>"


def _participants_count(target: Any) -> int:
    count = _get(target, "participants_count")
    if count is None:
        participants = _get(target, "participants")
        count = len(participants) if isinstance(participants, (list, tuple)) else 0
    try:
        return max(0, int(count))
    except (TypeError, ValueError):
        return 0


def _info_block(target: Any) -> str:
    lines = [f"**Quand :** {_when_text(target)}"]
    location = escape_markdown(_clip(str(_get(target, "location") or "").strip(), 200), single_line=True)
    if location:
        lines.append(f"**Où :** {location}")
    count = _participants_count(target)
    if count:
        lines.append(f"**Participants :** {count} personne{'s' if count > 1 else ''}")
    return _clip_escaped("\n".join(lines), MAX_TEXT_DISPLAY)


def _detail_title(item: Any) -> str:
    if isinstance(item, Mapping):
        item = item.get("title") or item.get("text") or ""
    return str(item or "").strip()


def _details_block(target: Any) -> str | None:
    details = _get(target, "details")
    is_meeting = _get(target, "kind") == "meeting"
    if isinstance(details, (list, tuple)):
        items = [title for title in (_detail_title(item) for item in details) if title]
        if not items:
            return None
        heading = "**Ordre du jour**" if is_meeting else "**Détails**"
        lines = [heading]
        size = len(heading)
        for index, title in enumerate(items, start=1):
            line = f"{index}. {escape_markdown(_clip(title, 200), single_line=True)}"
            if size + 1 + len(line) > MAX_TEXT_DISPLAY - 2:
                lines.append("…")
                break
            lines.append(line)
            size += 1 + len(line)
        return "\n".join(lines)

    text = str(details or "").strip()
    if not text:
        return None
    heading = "**Ordre du jour**" if is_meeting else "**Description**"
    body = _clip_escaped(escape_markdown(_clip(text, 600)), MAX_TEXT_DISPLAY - len(heading) - 1)
    return f"{heading}\n{body}"


def _mention_role(settings: Any, ping: bool) -> str | None:
    role_id = str(_get(settings, "ping_role_id") or "")
    if ping and _ROLE_ID.fullmatch(role_id):
        return role_id
    return None


def _frontend_url(settings: Any) -> str:
    base = _get(settings, "frontend_url") or os.getenv("FRONTEND_URL") or DEFAULT_FRONTEND_URL
    return str(base).strip().rstrip("/")


def _text(content: str) -> dict[str, Any]:
    return {"type": 10, "content": content}


def _separator() -> dict[str, Any]:
    return {"type": 14, "divider": True, "spacing": 1}


def _button_url(url: Any) -> str | None:
    """URL d'un bouton lien, ou None : Discord refuserait tout le message pour une URL mal formée."""
    url = str(url or "").strip()
    if not url.lower().startswith(("http://", "https://")) or len(url) > MAX_BUTTON_URL:
        return None
    if any(char.isspace() or not char.isprintable() for char in url):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if not parts.hostname or parts.username is not None or parts.password is not None:
        return None
    return url


def _link_row(label: str, url: Any) -> dict[str, Any] | None:
    url = _button_url(url)
    if url is None:
        return None
    return {"type": 1, "components": [{"type": 2, "style": 5, "label": label, "url": url}]}


def _text_length(components: list[dict[str, Any]]) -> int:
    total = 0
    for component in components:
        total += len(component.get("content") or "") + len(component.get("label") or "")
        total += _text_length(component.get("components") or [])
    return total


def _component_count(components: list[dict[str, Any]]) -> int:
    return sum(1 + _component_count(component.get("components") or []) for component in components)


def _finalize(nonce: str | None, role_id: str | None, accent: int, children: list[dict[str, Any]]) -> dict[str, Any]:
    for child in children:
        if child["type"] == 10:
            child["content"] = _clip_escaped(child["content"], MAX_TEXT_DISPLAY)

    components: list[dict[str, Any]] = [_text(f"<@&{role_id}>")] if role_id else []
    components.append({"type": 17, "accent_color": accent, "components": children})

    # Garde-fou : les plafonds par bloc tiennent déjà sous 3500 caractères ; on rogne le plus long sinon.
    while _text_length(components) > MAX_TOTAL_TEXT:
        longest = max((c for c in children if c["type"] == 10), key=lambda c: len(c["content"]))
        excess = _text_length(components) - MAX_TOTAL_TEXT
        longest["content"] = _clip_escaped(longest["content"], max(1, len(longest["content"]) - excess))
    if _component_count(components) > MAX_COMPONENTS:
        raise ValueError("Message Discord trop complexe.")

    payload: dict[str, Any] = {"flags": IS_COMPONENTS_V2}
    if nonce:
        payload["nonce"] = str(nonce)[:MAX_NONCE]
        payload["enforce_nonce"] = True
    payload["allowed_mentions"] = {"parse": [], "roles": [role_id] if role_id else []}
    payload["components"] = components
    return payload


def build_reminder_payload(target: Any, offset: str, settings: Any, *, ping: bool, nonce: str | None) -> dict[str, Any]:
    """Message de rappel Components V2 (ni `content` ni `embeds`) pour une réunion ou une entrée."""
    kind = _get(target, "kind")
    if kind not in REMINDABLE_KINDS:
        # Dernière barrière : une absence (ou toute autre cible) ne part jamais.
        raise ValueError(f"Cible de rappel refusée : {kind!r}.")
    if offset not in OFFSET_KEYS:
        raise ValueError(f"Palier de rappel inconnu : {offset!r}.")

    type_key = _get(target, "type_key") or ("reunion" if kind == "meeting" else "autre")
    emoji, default_label, accent = TYPE_STYLES.get(type_key, TYPE_STYLES["autre"])
    label = _clip(str(_get(target, "label") or default_label).strip(), 40) or default_label
    header = f"-# {emoji} {escape_markdown(label.upper(), single_line=True)} · RAPPEL {offset}"

    title = " ".join(str(_get(target, "title") or "").split()) or "Sans titre"
    children = [
        _text(header),
        _text(f"## {escape_markdown(_clip(title, MAX_TITLE), single_line=True)}"),
        _text(_info_block(target)),
    ]
    details = _details_block(target)
    if details:
        children += [_separator(), _text(details)]
    button = _link_row("Ouvrir dans Iris", _get(target, "url"))
    if button:
        children.append(button)
    children.append(_text("-# Rappel automatique d'Iris"))

    return _finalize(nonce, _mention_role(settings, ping), accent, children)


def build_test_payload(settings: Any, ping: bool = False, *, nonce: str | None = None) -> dict[str, Any]:
    """Message d'exemple envoyé depuis les réglages (même structure qu'un rappel)."""
    role_id = _mention_role(settings, ping)
    configured_role = _mention_role(settings, True)
    day_time = escape_markdown(str(_get(settings, "day_reminder_time") or "10:00"), single_line=True)

    info = [
        "**Paliers :** J-7, J-2, J-1 et H-1, selon les réglages de chaque élément",
        f"**Éléments sur la journée :** rappels à {day_time} (heure de Paris)",
        (f"**Rôle mentionné sur demande :** <@&{configured_role}>" if configured_role
         else "**Rôle mentionné :** aucun"),
    ]
    children = [
        _text("-# 🔔 MESSAGE DE TEST"),
        _text("## Rappels de l'agenda"),
        _text("Les rappels de l'agenda Iris arriveront dans ce salon."),
        _separator(),
        _text("\n".join(info)),
    ]
    button = _link_row("Ouvrir dans Iris", f"{_frontend_url(settings)}/staff/calendrier")
    if button:
        children.append(button)
    children.append(_text("-# Message de test envoyé depuis Iris"))

    return _finalize(nonce or f"agt{uuid.uuid4().hex[:22]}", role_id, TEST_ACCENT, children)


async def send_test_message(settings: Any, *, ping: bool = False) -> dict[str, Any]:
    """Envoie le message de test dans le salon des réglages. Lève une DiscordSendError en cas d'échec."""
    channel_id = _get(settings, "channel_id")
    message = await post_channel_message(channel_id, build_test_payload(settings, ping))
    message_id = message.get("id")
    return {"ok": True, "message_id": str(message_id) if message_id else None, "channel_id": str(channel_id)}


def to_http_exception(exc: DiscordSendError) -> HTTPException:
    """Traduit une erreur d'envoi en réponse HTTP pour l'interface (429 ou 502)."""
    if isinstance(exc, DiscordRateLimited):
        seconds = max(1, math.ceil(exc.retry_after))
        return HTTPException(
            status_code=429,
            detail=f"Discord limite les envois, réessayez dans {seconds} s.",
            headers={"Retry-After": str(seconds)},
        )
    if isinstance(exc, DiscordPermanentError):
        if exc.status is None:
            # Refus local (token absent, salon invalide) : le message dit déjà quoi corriger.
            return HTTPException(status_code=502, detail=exc.message)
        hints = {403: "403 : le bot peut-il écrire dans ce salon ?", 404: "404 : salon introuvable"}
        reason = hints.get(exc.status, str(exc.status) if exc.status is not None else "")
        detail = f"Discord a refusé le message ({reason})." if reason else "Discord a refusé le message."
        return HTTPException(status_code=502, detail=detail)
    if exc.status is not None:
        return HTTPException(status_code=502, detail=f"Discord ne répond pas ({exc.status}), réessayez.")
    return HTTPException(status_code=502, detail="Discord ne répond pas, réessayez.")
