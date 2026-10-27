"""Message Discord des rappels agenda (Components V2) et envoi REST, hors ligne (httpx.MockTransport)."""
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import security_harness as h  # noqa: F401  (environnement de test avant les imports de l'application)

import httpx
import pytest

import config
from services import agenda_discord

ROLE_ID = h.ROLE_IDS["staff"]
CHANNEL_ID = "500000000000000001"
_REAL_ASYNC_CLIENT = httpx.AsyncClient
# Fuseaux de membres possibles d'une communauté francophone, de UTC-10 à UTC+12.
STAFF_TIMEZONES = ("Europe/Paris", "Europe/London", "America/Montreal", "America/Guadeloupe", "America/Cayenne",
                   "America/Miquelon", "Indian/Reunion", "Pacific/Tahiti", "Pacific/Marquesas", "Pacific/Noumea",
                   "Pacific/Wallis")
# Enfants permis par Discord (Components V2) : premier niveau, Container (17), Action Row (1), Section (9).
V2_CHILDREN = {None: {1, 9, 10, 12, 13, 14, 17}, 17: {1, 9, 10, 12, 13, 14}, 1: {2, 3, 5, 6, 7, 8}, 9: {10}}


@dataclass
class Target:
    kind: str = "meeting"
    id: str = "c9c09a61-84b5-428e-b5d8-d4137abba44f"
    type_key: str = "reunion"
    label: str = "Réunion"
    title: str = "Réunion mensuelle de novembre"
    start_date: str = "2026-10-30"
    start_time: str | None = "20:30"
    end_date: str | None = None
    end_time: str | None = None
    all_day: bool = False
    location: str = "Vocal Staff"
    details: object = field(default_factory=lambda: ["Tour de table", "Planning des permanences", "Divers"])
    participants_count: int = 6
    url: str = "https://iris.example.test/staff/meetings/c9c09a61-84b5-428e-b5d8-d4137abba44f"
    event_at: datetime | None = None


def _settings(**overrides):
    values = {"channel_id": CHANNEL_ID, "ping_role_id": ROLE_ID, "day_reminder_time": "10:00",
              "frontend_url": "https://iris.example.test"}
    values.update(overrides)
    return SimpleNamespace(**values)


def _ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def _container(payload):
    container = payload["components"][-1]
    assert container["type"] == 17
    return container


def _texts(payload):
    return [c["content"] for c in _container(payload)["components"] if c["type"] == 10]


def _buttons(payload):
    return [b for row in _container(payload)["components"] if row["type"] == 1 for b in row["components"]]


def _count(components):
    return sum(1 + _count(c.get("components") or []) for c in components)


def _text_size(components):
    return sum(len(c.get("content") or "") + len(c.get("label") or "") + _text_size(c.get("components") or [])
               for c in components)


def _discord_errors(payload):
    """Règles de POST /channels/{id}/messages qu'un message Components V2 doit respecter (sinon 400)."""
    errors = []
    if not payload.get("flags", 0) & 32768:
        errors.append("flags sans IS_COMPONENTS_V2")
    errors += [f"{key} interdit" for key in ("content", "embeds", "stickers", "poll") if key in payload]
    nonce = payload.get("nonce")
    if nonce is not None and (not isinstance(nonce, str) or not 0 < len(nonce) <= 25):
        errors.append("nonce invalide")
    if payload.get("enforce_nonce") and nonce is None:
        errors.append("enforce_nonce sans nonce")
    mentions = payload.get("allowed_mentions")
    if not isinstance(mentions, dict) or mentions.get("parse") != []:
        errors.append("allowed_mentions.parse doit être vide")
    elif not all(re.fullmatch(r"[0-9]{17,20}", role) for role in mentions.get("roles", [])):
        errors.append("allowed_mentions.roles invalide")

    total = text = 0

    def walk(components, parent):
        nonlocal total, text
        for item in components:
            total += 1
            kind = item.get("type")
            if kind not in V2_CHILDREN.get(parent, set()):
                errors.append(f"type {kind} interdit sous {parent}")
            if kind == 10:
                if not isinstance(item.get("content"), str) or not item["content"].strip():
                    errors.append("Text Display vide")
                else:
                    text += len(item["content"])
            elif kind == 17:
                accent = item.get("accent_color")
                if accent is not None and not (isinstance(accent, int) and 0 <= accent <= 0xFFFFFF):
                    errors.append("accent_color invalide")
            elif kind == 14:
                if not isinstance(item.get("divider"), bool) or item.get("spacing") not in (1, 2):
                    errors.append("Separator invalide")
            elif kind == 1 and not 1 <= len(item.get("components") or []) <= 5:
                errors.append("Action Row : 1 à 5 boutons")
            elif kind == 2:
                url = item.get("url") or ""
                if item.get("style") != 5 or "custom_id" in item or not url.startswith(("http://", "https://")):
                    errors.append("bouton lien invalide")
                if len(url) > 512 or not 0 < len(item.get("label") or "") <= 80:
                    errors.append("bouton trop long")
            if kind in (1, 17):
                if not item.get("components"):
                    errors.append(f"composant {kind} vide")
                walk(item.get("components") or [], kind)

    walk(payload.get("components") or [], None)
    if not total:
        errors.append("message vide")
    if total > 40 or text > 4000:
        errors.append("message trop grand")
    return errors


def _day_stamps(text):
    return [int(stamp) for stamp in re.findall(r"<t:(\d+):D>", text)]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Toute requête httpx non simulée échoue : aucun test ne peut joindre Discord."""
    def refuse(request):
        raise AssertionError(f"Requête réseau inattendue : {request.url}")

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(refuse)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr(agenda_discord.httpx, "AsyncClient", factory)
    monkeypatch.setattr(config, "DISCORD_BOT_TOKEN", "faux-token-de-test")


class _Recorded(list):
    """Requêtes reçues par le faux Discord ; `clients` garde les arguments de chaque httpx.AsyncClient créé."""

    def __init__(self):
        super().__init__()
        self.clients = []


def _mock_discord(monkeypatch, handler):
    """Remplace httpx.AsyncClient du module par une fabrique qui injecte un MockTransport."""
    calls = _Recorded()

    def recording(request):
        calls.append(request)
        return handler(request)

    def factory(*args, **kwargs):
        calls.clients.append(dict(kwargs))
        kwargs["transport"] = httpx.MockTransport(recording)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr(agenda_discord.httpx, "AsyncClient", factory)
    return calls


# --- Construction du message ---------------------------------------------------------------

def test_meeting_payload_matches_components_v2_contract():
    nonce = "agd0123456789abcdef012345"
    payload = agenda_discord.build_reminder_payload(Target(), "J-2", _settings(), ping=True, nonce=nonce)

    assert payload["flags"] == 32768
    assert "content" not in payload and "embeds" not in payload
    assert payload["nonce"] == nonce and len(payload["nonce"]) <= 25
    assert payload["enforce_nonce"] is True
    assert payload["allowed_mentions"] == {"parse": [], "roles": [ROLE_ID]}
    assert payload["components"][0] == {"type": 10, "content": f"<@&{ROLE_ID}>"}

    container = _container(payload)
    assert container["accent_color"] == 4810125 == 0x49658D
    start = _ts("2026-10-30T19:30:00Z")  # 20:30 à Paris (heure d'hiver)
    assert [c["type"] for c in container["components"]] == [10, 10, 10, 14, 10, 1, 10]
    assert _texts(payload) == [
        "-# 🗓️ RÉUNION · RAPPEL J-2",
        "## Réunion mensuelle de novembre",
        f"**Quand :** <t:{start}:F> · <t:{start}:R>\n**Où :** Vocal Staff\n**Participants :** 6 personnes",
        "**Ordre du jour**\n1. Tour de table\n2. Planning des permanences\n3. Divers",
        "-# Rappel automatique d'Iris",
    ]
    assert container["components"][3] == {"type": 14, "divider": True, "spacing": 1}
    assert _buttons(payload) == [{"type": 2, "style": 5, "label": "Ouvrir dans Iris", "url": Target().url}]
    assert _count(payload["components"]) <= 12
    json.dumps(payload)  # sérialisable tel quel


def test_no_mention_without_ping_or_without_configured_role():
    for settings, ping in ((_settings(), False), (_settings(ping_role_id=None), True),
                           (_settings(ping_role_id=""), True), (_settings(ping_role_id="everyone"), True)):
        payload = agenda_discord.build_reminder_payload(Target(), "J-1", settings, ping=ping, nonce="agd1")
        assert payload["allowed_mentions"] == {"parse": [], "roles": []}
        assert len(payload["components"]) == 1
        assert all("<@&" not in text for text in _texts(payload))


def test_settings_and_target_can_be_dicts():
    target = {**Target().__dict__, "kind": "entry", "type_key": "permanence", "label": "Permanence"}
    payload = agenda_discord.build_reminder_payload(target, "H-1", {"ping_role_id": ROLE_ID}, ping=True, nonce="agd2")
    assert payload["allowed_mentions"]["roles"] == [ROLE_ID]
    assert _texts(payload)[0] == "-# 🎧 PERMANENCE · RAPPEL H-1"
    assert _container(payload)["accent_color"] == 0x4A675C


def test_dst_and_end_time_formats():
    # Lendemain du passage à l'heure d'hiver : 20:00 à Paris = 19:00Z.
    payload = agenda_discord.build_reminder_payload(
        Target(start_date="2026-10-26", start_time="20:00", end_time="21:30"), "J-1", _settings(),
        ping=False, nonce="n")
    start, end = _ts("2026-10-26T19:00:00Z"), _ts("2026-10-26T20:30:00Z")
    assert _texts(payload)[2].startswith(f"**Quand :** <t:{start}:F> → <t:{end}:t> · <t:{start}:R>\n")

    # Heure d'été : 20:00 à Paris = 18:00Z.
    payload = agenda_discord.build_reminder_payload(
        Target(start_date="2026-10-20", start_time="20:00"), "J-7", _settings(), ping=False, nonce="n")
    assert f"<t:{_ts('2026-10-20T18:00:00Z')}:F>" in _texts(payload)[2]

    # Entrée horaire sur plusieurs jours avec heure de fin : date complète à la fin.
    payload = agenda_discord.build_reminder_payload(
        Target(kind="entry", type_key="evenement", label="Événement", start_date="2026-10-29", start_time="20:30",
               end_date="2026-10-31", end_time="18:00"), "J-2", _settings(), ping=False, nonce="n")
    start, end = _ts("2026-10-29T19:30:00Z"), _ts("2026-10-31T17:00:00Z")
    assert f"**Quand :** <t:{start}:F> → <t:{end}:f> · <t:{start}:R>" in _texts(payload)[2]


def test_all_day_single_and_multi_day():
    single = Target(kind="entry", type_key="echeance", label="Échéance", title="Clôture des candidatures helper",
                    start_date="2026-11-03", start_time=None, all_day=True, location="", details="",
                    participants_count=0,
                    url="https://iris.example.test/staff/calendrier?date=2026-11-03&element=entry:e1")
    payload = agenda_discord.build_reminder_payload(single, "J-1", _settings(), ping=False, nonce="n")
    noon = _ts("2026-11-03T11:00:00Z")  # midi à Paris (heure d'hiver)
    texts = _texts(payload)
    assert texts[0] == "-# ⏳ ÉCHÉANCE · RAPPEL J-1"
    assert texts[2] == f"**Quand :** <t:{noon}:D> (toute la journée)"
    assert _container(payload)["accent_color"] == 0x954C50
    # Pas de lieu, pas de participants, pas de détails : ni lignes ni séparateur.
    assert [c["type"] for c in _container(payload)["components"]] == [10, 10, 10, 1, 10]
    assert "entry:e1" in _buttons(payload)[0]["url"]

    multi = Target(kind="entry", type_key="evenement", label="Événement", start_date="2026-10-30",
                   end_date="2026-11-02", start_time=None, all_day=True)
    payload = agenda_discord.build_reminder_payload(multi, "J-7", _settings(), ping=False, nonce="n")
    assert _texts(payload)[2].startswith(
        f"**Quand :** <t:{_ts('2026-10-30T11:00:00Z')}:D> → <t:{_ts('2026-11-02T11:00:00Z')}:D>\n")

    # Fin le même jour que le début : une seule date.
    same_day = Target(kind="entry", type_key="rappel", start_date="2026-07-14", end_date="2026-07-14",
                      start_time=None, all_day=True)
    payload = agenda_discord.build_reminder_payload(same_day, "J-1", _settings(), ping=False, nonce="n")
    assert _texts(payload)[2].startswith(f"**Quand :** <t:{_ts('2026-07-14T10:00:00Z')}:D> (toute la journée)")

    # Réunion sans heure : affichée sur la journée.
    payload = agenda_discord.build_reminder_payload(Target(start_time=None), "J-1", _settings(), ping=False, nonce="n")
    assert "(toute la journée)" in _texts(payload)[2]


def test_all_day_date_is_right_in_every_staff_timezone():
    # <t:X:D> s'affiche dans le fuseau du lecteur : la date doit rester celle de Paris, de Tahiti à Wallis,
    # y compris les jours de changement d'heure.
    for day in ("2026-01-15", "2026-03-29", "2026-07-15", "2026-10-25", "2026-12-31"):
        target = Target(kind="entry", type_key="evenement", start_date=day, end_date="2027-01-02",
                        start_time=None, all_day=True)
        when = _texts(agenda_discord.build_reminder_payload(target, "J-1", _settings(), ping=False, nonce="n"))[2]
        start, end = _day_stamps(when)
        for name in STAFF_TIMEZONES:
            zone = ZoneInfo(name)
            assert datetime.fromtimestamp(start, zone).date().isoformat() == day, (day, name)
            assert datetime.fromtimestamp(end, zone).date().isoformat() == "2027-01-02", (day, name)

    # Entrée horaire sur plusieurs jours sans heure de fin : la date de fin suit la même règle.
    timed = Target(kind="entry", type_key="evenement", start_date="2026-10-30", start_time="20:30",
                   end_date="2026-11-01")
    when = _texts(agenda_discord.build_reminder_payload(timed, "J-1", _settings(), ping=False, nonce="n"))[2]
    assert f"→ <t:{_ts('2026-11-01T11:00:00Z')}:D> · <t:{_ts('2026-10-30T19:30:00Z')}:R>" in when


def test_entry_types_emoji_and_custom_label():
    expected = {"evenement": ("🎉", 0x765094), "echeance": ("⏳", 0x954C50), "rappel": ("🔔", 0x88672E),
                "permanence": ("🎧", 0x4A675C), "autre": ("📌", 0x64706A)}
    for type_key, (emoji, color) in expected.items():
        label = "Formation" if type_key == "autre" else agenda_discord.TYPE_STYLES[type_key][1]
        payload = agenda_discord.build_reminder_payload(
            Target(kind="entry", type_key=type_key, label=label), "J-1", _settings(), ping=False, nonce="n")
        assert _texts(payload)[0] == f"-# {emoji} {label.upper()} · RAPPEL J-1"
        assert _container(payload)["accent_color"] == color

    payload = agenda_discord.build_reminder_payload(
        Target(kind="entry", type_key="evenement", details="Among Us puis karaoké.", participants_count=1),
        "J-1", _settings(), ping=False, nonce="n")
    texts = _texts(payload)
    assert "**Participants :** 1 personne" in texts[2]
    assert texts[3] == "**Description**\nAmong Us puis karaoké."

    # Participants donnés en liste, sans compteur.
    target = {**Target().__dict__, "participants_count": None, "participants": [{"id": "1"}, {"id": "2"}]}
    payload = agenda_discord.build_reminder_payload(target, "J-1", _settings(), ping=False, nonce="n")
    assert "**Participants :** 2 personnes" in _texts(payload)[2]

    # Réunion dont l'ordre du jour arrive en texte : même intitulé que la liste.
    payload = agenda_discord.build_reminder_payload(Target(details="Tour de table"), "J-1", _settings(),
                                                    ping=False, nonce="n")
    assert _texts(payload)[3] == "**Ordre du jour**\nTour de table"


def test_button_only_for_http_urls():
    # Une URL mal formée ferait refuser tout le message (400) : pas de bouton plutôt qu'un rappel perdu.
    for url in ("", None, "/staff/meetings/x", "javascript:alert(1)", "discord://x", "https://a.b/x y",
                "https://iris.example.test/" + "a" * 600, "https://", "https:///staff/meetings/x",
                "https://:443/x", "https://user:secret@iris.example.test/x", "https://@iris.example.test/x",
                "https://[::1/x", "https://iris.example.test/x\x00y", "https://iris.example.test/​x"):
        payload = agenda_discord.build_reminder_payload(Target(url=url), "J-1", _settings(), ping=False, nonce="n")
        assert _buttons(payload) == [], url
        assert _texts(payload)[-1] == "-# Rappel automatique d'Iris"
        assert _discord_errors(payload) == []
    for url in ("http://localhost:3000/staff/meetings/x", "  https://iris.example.test/staff/meetings/x  ",
                "https://iris.example.test/staff/calendrier?date=2026-10-29&element=entry:e1"):
        payload = agenda_discord.build_reminder_payload(Target(url=url), "J-1", _settings(), ping=False, nonce="n")
        assert _buttons(payload)[0]["url"] == url.strip()


def test_lengths_are_capped():
    target = Target(
        title="T" * 400,
        location="L" * 500,
        details=[("point " * 80).strip() for _ in range(50)],
    )
    payload = agenda_discord.build_reminder_payload(target, "J-1", _settings(), ping=True, nonce="x" * 40)
    texts = _texts(payload)
    assert len(texts[1]) <= len("## ") + 160
    assert all(len(text) <= 1000 for text in texts)
    assert texts[3].endswith("…")
    assert _text_size(payload["components"]) <= 3500
    assert _count(payload["components"]) <= 12
    assert len(payload["nonce"]) == 25

    long_description = Target(kind="entry", type_key="rappel", details="*" * 2000)
    payload = agenda_discord.build_reminder_payload(long_description, "J-1", _settings(), ping=False, nonce="n")
    description = _texts(payload)[3]
    assert len(description) <= 1000
    assert description.endswith("…") and not description.endswith("\\…")


def test_user_text_is_escaped():
    target = Target(
        title="**Gras**\n# Titre @everyone",
        location="> Vocal _staff_ <@&123456789012345678> https://discord.gg/a_b*c",
        details=["@here ~~barré~~", "-# petit", "[lien](https://evil.example)", "`code` | tube \\"],
    )
    payload = agenda_discord.build_reminder_payload(target, "J-1", _settings(), ping=False, nonce="n")
    texts = _texts(payload)
    assert texts[1] == "## \\*\\*Gras\\*\\* # Titre @\u200beveryone"
    assert "**Où :** \\> Vocal \\_staff\\_ \\<@&123456789012345678> https://discord.gg/a_b*c" in texts[2]
    assert texts[3] == ("**Ordre du jour**\n1. @\u200bhere \\~\\~barré\\~\\~\n2. \\-# petit\n"
                        "3. \\[lien](https://evil.example)\n4. \\`code\\` \\| tube \\\\")
    assert payload["allowed_mentions"] == {"parse": [], "roles": []}


def test_escape_markdown_helper():
    escape = agenda_discord.escape_markdown
    assert escape("# Titre\n> cite\n  - puce") == "\\# Titre\n\\> cite\n  \\- puce"
    assert escape("ligne 1\nligne 2", single_line=True) == "ligne 1 ligne 2"
    assert escape("@Everyone et @HERE") == "@\u200bEveryone et @\u200bHERE"
    assert escape(None) == ""
    assert escape("a#b > c") == "a#b > c"
    # Caract\u00e8res de contr\u00f4le retir\u00e9s (tabulation et retours \u00e0 la ligne gard\u00e9s).
    assert escape("a\x00b\x07c\td\x0be\x7ff\r\ng") == "abc\tdef\ng"
    assert escape("Titre\x1b[31m\nrouge", single_line=True) == "Titre\\[31m rouge"
    assert escape("\x00# Titre") == "\\# Titre"


def test_payloads_pass_discord_structure_checks():
    payloads = [
        agenda_discord.build_reminder_payload(Target(), "J-2", _settings(), ping=True, nonce="agd" + "0" * 22),
        agenda_discord.build_reminder_payload(Target(start_time=None, details=[], participants_count=0, location=""),
                                              "J-1", _settings(), ping=False, nonce="n"),
        agenda_discord.build_test_payload(_settings(), False),
        agenda_discord.build_test_payload(_settings(), True),
        agenda_discord.build_test_payload(_settings(ping_role_id=None), True),
    ]
    for type_key, (_emoji, label, _accent) in agenda_discord.TYPE_STYLES.items():
        kind = "meeting" if type_key == "reunion" else "entry"
        details = ["Point"] if kind == "meeting" else "Description **libre**\n# avec @everyone"
        for offset in agenda_discord.OFFSET_KEYS:
            payloads.append(agenda_discord.build_reminder_payload(
                Target(kind=kind, type_key=type_key, label=label, details=details),
                offset, _settings(), ping=offset == "H-1", nonce="agd" + offset))
    # Textes au maximum partout, et textes faits de caractères à échapper.
    payloads.append(agenda_discord.build_reminder_payload(
        Target(title="é*" * 200, location="_" * 400, details=["`" * 300] * 50, participants_count=50, label="L" * 80),
        "J-7", _settings(), ping=True, nonce="x" * 60))
    payloads.append(agenda_discord.build_reminder_payload(
        Target(kind="entry", type_key="autre", label="\\" * 100, title="\\" * 500, details="\\" * 2000),
        "H-1", _settings(), ping=False, nonce="n"))

    for payload in payloads:
        assert _discord_errors(payload) == [], payload
        json.dumps(payload)
        for text in _texts(payload):
            assert len(text) <= 1000
            # Une coupure ne laisse jamais une barre oblique seule devant « … » (elle l'échapperait).
            run = re.search(r"(\\*)…$", text)
            assert run is None or len(run.group(1)) % 2 == 0, text


def test_absences_and_unknown_offsets_are_refused():
    with pytest.raises(ValueError):
        agenda_discord.build_reminder_payload(Target(kind="absence", type_key="absence"), "J-1", _settings(),
                                              ping=False, nonce="n")
    with pytest.raises(ValueError):
        agenda_discord.build_reminder_payload(Target(), "J-3", _settings(), ping=False, nonce="n")


def test_unreadable_dates_fall_back_to_event_at():
    event_at = datetime(2026, 10, 30, 19, 30)  # naïf, lu comme UTC (relecture Mongo)
    payload = agenda_discord.build_reminder_payload(
        Target(start_date="30/10/2026", event_at=event_at), "J-1", _settings(), ping=False, nonce="n")
    ts = int(event_at.replace(tzinfo=timezone.utc).timestamp())
    assert _texts(payload)[2].startswith(f"**Quand :** <t:{ts}:F> · <t:{ts}:R>")
    with pytest.raises(ValueError):
        agenda_discord.build_reminder_payload(Target(start_date="?"), "J-1", _settings(), ping=False, nonce="n")


def test_test_payload_structure_and_mention():
    payload = agenda_discord.build_test_payload(_settings(), False)
    assert payload["flags"] == 32768
    assert "content" not in payload and "embeds" not in payload
    assert payload["allowed_mentions"] == {"parse": [], "roles": []}
    assert payload["enforce_nonce"] is True and 0 < len(payload["nonce"]) <= 25
    assert len(payload["components"]) == 1
    texts = _texts(payload)
    assert texts[0] == "-# 🔔 MESSAGE DE TEST"
    assert "Les rappels de l'agenda Iris arriveront dans ce salon." in texts
    assert _buttons(payload)[0]["url"] == "https://iris.example.test/staff/calendrier"
    assert _count(payload["components"]) <= 12

    pinged = agenda_discord.build_test_payload(_settings(), True)
    assert pinged["components"][0] == {"type": 10, "content": f"<@&{ROLE_ID}>"}
    assert pinged["allowed_mentions"] == {"parse": [], "roles": [ROLE_ID]}
    assert pinged["nonce"] != payload["nonce"]

    no_role = agenda_discord.build_test_payload(_settings(ping_role_id=None), True)
    assert no_role["allowed_mentions"] == {"parse": [], "roles": []}
    assert any("**Rôle mentionné :** aucun" in text for text in _texts(no_role))


def test_test_payload_uses_frontend_url_env(monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", "https://preprod.example.test/")
    payload = agenda_discord.build_test_payload(SimpleNamespace(ping_role_id=None), False)
    assert _buttons(payload)[0]["url"] == "https://preprod.example.test/staff/calendrier"


# --- Envoi REST ----------------------------------------------------------------------------

def test_post_channel_message_sends_expected_request(monkeypatch):
    payload = agenda_discord.build_reminder_payload(Target(), "J-1", _settings(), ping=True, nonce="agd" + "0" * 22)
    calls = _mock_discord(monkeypatch, lambda request: httpx.Response(200, json={"id": "600000000000000001"}))

    result = h.run(agenda_discord.post_channel_message(CHANNEL_ID, payload))

    assert result == {"id": "600000000000000001"}
    assert len(calls) == 1
    assert calls.clients[0]["timeout"] == 10
    request = calls[0]
    assert request.method == "POST"
    assert str(request.url) == f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"
    assert request.headers["authorization"] == "Bot faux-token-de-test"
    assert request.headers["user-agent"].startswith("DiscordBot (")
    body = json.loads(request.content)
    assert body == payload
    assert body["flags"] == 32768 and body["enforce_nonce"] is True


def test_post_channel_message_maps_errors(monkeypatch):
    cases = [
        (lambda r: httpx.Response(429, json={"retry_after": 2.5, "global": False}), agenda_discord.DiscordRateLimited),
        (lambda r: httpx.Response(429, headers={"Retry-After": "7"}, text="slow down"),
         agenda_discord.DiscordRateLimited),
        (lambda r: httpx.Response(429, text="<html>"), agenda_discord.DiscordRateLimited),
        (lambda r: httpx.Response(503, text="indisponible"), agenda_discord.DiscordTemporaryError),
        (lambda r: httpx.Response(500, json={"message": "Internal"}), agenda_discord.DiscordTemporaryError),
        (lambda r: httpx.Response(403, json={"message": "Missing Permissions", "code": 50013}),
         agenda_discord.DiscordPermanentError),
        (lambda r: httpx.Response(404, json={"message": "Unknown Channel", "code": 10003}),
         agenda_discord.DiscordPermanentError),
        (lambda r: httpx.Response(400, text="x" * 2000), agenda_discord.DiscordPermanentError),
    ]
    raised = []
    for handler, expected in cases:
        _mock_discord(monkeypatch, handler)
        with pytest.raises(expected) as info:
            h.run(agenda_discord.post_channel_message(CHANNEL_ID, {"flags": 32768}))
        raised.append(info.value)

    assert [e.retry_after for e in raised[:3]] == [2.5, 7.0, 5.0]
    assert all(e.status == 429 for e in raised[:3])
    assert raised[3].status == 503 and "indisponible" in str(raised[3])
    assert raised[5].status == 403 and str(raised[5]) == "HTTP 403 : Missing Permissions (code 50013)"
    assert raised[6].status == 404
    assert raised[7].status == 400 and len(str(raised[7])) <= 300
    assert all(not isinstance(e, agenda_discord.DiscordPermanentError) for e in raised[:5])


def test_post_channel_message_network_errors_are_temporary(monkeypatch):
    def connect_error(request):
        raise httpx.ConnectError("connexion refusée", request=request)

    def timeout(request):
        raise httpx.ReadTimeout("délai dépassé", request=request)

    for handler in (connect_error, timeout):
        _mock_discord(monkeypatch, handler)
        with pytest.raises(agenda_discord.DiscordTemporaryError) as info:
            h.run(agenda_discord.post_channel_message(CHANNEL_ID, {"flags": 32768}))
        assert info.value.status is None
        assert len(str(info.value)) <= 300


def test_post_channel_message_rejects_bad_channel_and_missing_token(monkeypatch):
    calls = _mock_discord(monkeypatch, lambda request: httpx.Response(200, json={"id": "1"}))
    for channel_id in ("../users/@me", "", None, "12 3"):
        with pytest.raises(agenda_discord.DiscordPermanentError):
            h.run(agenda_discord.post_channel_message(channel_id, {"flags": 32768}))

    monkeypatch.setattr(config, "DISCORD_BOT_TOKEN", "")
    with pytest.raises(agenda_discord.DiscordPermanentError) as info:
        h.run(agenda_discord.post_channel_message(CHANNEL_ID, {"flags": 32768}))
    assert info.value.status is None and "DISCORD_BOT_TOKEN" in str(info.value)
    assert calls == []


def test_post_channel_message_tolerates_odd_success_bodies(monkeypatch):
    _mock_discord(monkeypatch, lambda request: httpx.Response(200, text="pas du json"))
    assert h.run(agenda_discord.post_channel_message(CHANNEL_ID, {})) == {}
    _mock_discord(monkeypatch, lambda request: httpx.Response(200, json=["liste"]))
    assert h.run(agenda_discord.post_channel_message(CHANNEL_ID, {})) == {}


# --- Message de test et erreurs HTTP --------------------------------------------------------

def test_send_test_message_goes_through_substitutable_sender(monkeypatch):
    sent = []

    async def fake_post(channel_id, payload):
        sent.append((channel_id, payload))
        return {"id": "600000000000000002"}

    monkeypatch.setattr(agenda_discord, "post_channel_message", fake_post)
    result = h.run(agenda_discord.send_test_message(_settings(), ping=True))

    assert result == {"ok": True, "message_id": "600000000000000002", "channel_id": CHANNEL_ID}
    assert len(sent) == 1 and sent[0][0] == CHANNEL_ID
    assert sent[0][1]["allowed_mentions"] == {"parse": [], "roles": [ROLE_ID]}
    assert _texts(sent[0][1])[0] == "-# 🔔 MESSAGE DE TEST"


def test_send_test_message_end_to_end_with_mock_transport(monkeypatch):
    calls = _mock_discord(monkeypatch, lambda request: httpx.Response(200, json={"id": "600000000000000003"}))
    result = h.run(agenda_discord.send_test_message(_settings()))
    assert result["message_id"] == "600000000000000003"
    assert json.loads(calls[0].content)["allowed_mentions"] == {"parse": [], "roles": []}

    _mock_discord(monkeypatch, lambda request: httpx.Response(403, json={"message": "Missing Access"}))
    with pytest.raises(agenda_discord.DiscordPermanentError):
        h.run(agenda_discord.send_test_message(_settings()))


def test_to_http_exception_messages():
    to_http = agenda_discord.to_http_exception

    limited = to_http(agenda_discord.DiscordRateLimited(2.5))
    assert limited.status_code == 429
    assert limited.detail == "Discord limite les envois, réessayez dans 3 s."
    assert limited.headers == {"Retry-After": "3"}

    refused = to_http(agenda_discord.DiscordPermanentError(403))
    assert refused.status_code == 502
    assert refused.detail == "Discord a refusé le message (403 : le bot peut-il écrire dans ce salon ?)."
    assert to_http(agenda_discord.DiscordPermanentError(400, "x")).detail == "Discord a refusé le message (400)."
    local = to_http(agenda_discord.DiscordPermanentError(None, "Envoi impossible : DISCORD_BOT_TOKEN non défini."))
    assert (local.status_code, local.detail) == (502, "Envoi impossible : DISCORD_BOT_TOKEN non défini.")

    down = to_http(agenda_discord.DiscordTemporaryError(None, "timeout"))
    assert (down.status_code, down.detail) == (502, "Discord ne répond pas, réessayez.")
    assert to_http(agenda_discord.DiscordTemporaryError(503, "x")).detail == "Discord ne répond pas (503), réessayez."


def test_exception_shapes():
    limited = agenda_discord.DiscordRateLimited(2.5)
    assert limited.retry_after == 2.5 and limited.status == 429
    temporary = agenda_discord.DiscordTemporaryError(None, "timeout")
    assert temporary.status is None and str(temporary) == "timeout"
    permanent = agenda_discord.DiscordPermanentError(403)
    assert permanent.status == 403 and str(permanent)
    assert len(str(agenda_discord.DiscordPermanentError(400, "y" * 1000))) == 300
    for exc in (limited, temporary, permanent):
        assert isinstance(exc, agenda_discord.DiscordSendError)


def test_works_with_effective_settings_dataclass():
    try:
        from services.agenda_settings import EffectiveSettings
    except Exception as exc:  # module d'un autre lot, éventuellement en cours d'écriture
        pytest.skip(f"agenda_settings indisponible : {exc}")
    settings = EffectiveSettings(channel_id=CHANNEL_ID, ping_role_id=ROLE_ID, frontend_url="https://iris.example.test")

    reminder = agenda_discord.build_reminder_payload(Target(), "J-1", settings, ping=True, nonce="agd3")
    assert reminder["allowed_mentions"] == {"parse": [], "roles": [ROLE_ID]}
    test_message = agenda_discord.build_test_payload(settings, False)
    assert _buttons(test_message)[0]["url"] == "https://iris.example.test/staff/calendrier"
    assert any("10:00" in text for text in _texts(test_message))
