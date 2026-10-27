"""Tests hors ligne du métier de l'agenda : absences, entrées et réunions (services, sans routeur).

Lancer depuis backend/ : python -m pytest -q -p no:cacheprovider -n 0 tests/test_agenda_domain.py
"""
import security_harness as h  # noqa: I001  (doit être importé en premier)

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from database import db
from models.staff import AbsenceReturn
from models.ticket import AuthenticatedHelper
from services import agenda_absences, agenda_entries, agenda_meetings, agenda_people, agenda_time
from services import discord_service
from services.discord_service import DiscordService

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)  # 13:00 à Paris (heure d'hiver depuis 03:00)

STAFF = "400000000000000003"
RESP = "400000000000000004"
ANIM = "400000000000000005"
OTHER = "400000000000000077"
GONE = "400000000000000088"
UNKNOWN = "400000000000000999"

VIEWER_STAFF = {"id": STAFF, "is_responsable": False}
VIEWER_RESP = {"id": RESP, "is_responsable": True}
VIEWER_OTHER = {"id": OTHER, "is_responsable": False}


def helper_of(person_id: str, name: str = "membre") -> AuthenticatedHelper:
    return AuthenticatedHelper(id=person_id, username=name, global_name=name.capitalize())


H_STAFF = helper_of(STAFF, "staff")
H_RESP = helper_of(RESP, "responsable")
H_OTHER = helper_of(OTHER, "autre")


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    h.reset_db()
    h.reset_discord()
    agenda_people.reset_state()
    monkeypatch.setattr(agenda_time, "now_utc", lambda: NOW)
    # Annuaire staff : trois membres, plus un membre parti dont l'identité reste stockée.
    for member_id in (STAFF, RESP, ANIM):
        if h.ROLE_IDS["staff"] not in h.fake_discord.member_roles.setdefault(member_id, []):
            h.fake_discord.member_roles[member_id].append(h.ROLE_IDS["staff"])
    yield
    agenda_people.reset_state()


def set_clock(monkeypatch, moment: datetime) -> None:
    monkeypatch.setattr(agenda_time, "now_utc", lambda: moment)


def raises_http(coroutine_or_call, status_code: int, detail: str | None = None) -> None:
    with pytest.raises(HTTPException) as error:
        if hasattr(coroutine_or_call, "__await__"):
            h.run(coroutine_or_call)
        else:
            coroutine_or_call()
    assert error.value.status_code == status_code
    if detail is not None:
        assert error.value.detail == detail


def insert(collection: str, doc: dict) -> dict:
    h.run(getattr(db, collection).insert_one(dict(doc)))
    return doc


def stored(collection: str, doc_id: str) -> dict:
    return h.run(getattr(db, collection).find_one({"id": doc_id}, {"_id": 0}))


# ---------------------------------------------------------------------------
# Absences
# ---------------------------------------------------------------------------

def person(person_id: str, name: str = "membre") -> dict:
    return {"id": person_id, "username": name, "display_name": None, "avatar_url": None}


def absence_doc(absence_id: str, start: str, end: str | None, *, open_ended: bool | None = None, helper_id: str = STAFF,
                **extra) -> dict:
    doc = {"id": absence_id, "helper": person(helper_id), "start_date": start, "end_date": end,
           "reason": "", "created_at": "2026-10-01T08:00:00+00:00", **extra}
    if open_ended is not None:
        doc["open_ended"] = open_ended
    return doc


def test_absence_phase_covers_every_case_and_legacy_documents():
    today = "2026-10-25"
    assert agenda_absences.phase(absence_doc("a", "2026-10-05", "2026-10-10"), today) == "passee"
    assert agenda_absences.phase(absence_doc("a", "2026-10-23", "2026-10-28"), today) == "en_cours"
    assert agenda_absences.phase(absence_doc("a", "2026-10-25", "2026-10-25"), today) == "en_cours"
    assert agenda_absences.phase(absence_doc("a", "2026-10-24", "2026-10-24"), today) == "passee"
    assert agenda_absences.phase(absence_doc("a", "2026-11-03", "2026-11-05"), today) == "a_venir"
    assert agenda_absences.phase(absence_doc("a", "2026-10-01", None, open_ended=True), today) == "en_cours"
    assert agenda_absences.phase(absence_doc("a", "2026-11-01", None, open_ended=True), today) == "a_venir"
    # Ancien document : ni `open_ended` ni `end_date`, lu comme sans fin.
    legacy = absence_doc("a", "2026-10-01", None)
    assert agenda_absences.phase(legacy, today) == "en_cours"
    assert agenda_absences.is_open_ended(legacy) is True
    assert agenda_absences.is_open_ended(absence_doc("a", "2026-10-01", "2026-10-02")) is False
    # Sans date du jour fournie : celle de Paris (figée par la fixture).
    assert agenda_absences.phase(absence_doc("a", "2026-10-05", "2026-10-10")) == "passee"


def test_absence_to_out_shape_and_can_edit():
    doc = absence_doc("a1", "2026-10-22", None, open_ended=True, reason="Indisponible", created_by=person(STAFF))
    out = agenda_absences.to_out(doc, VIEWER_STAFF)

    assert out["end_date"] is None and out["open_ended"] is True and out["phase"] == "en_cours"
    assert out["helper"]["id"] == STAFF and out["created_by"]["id"] == STAFF
    assert out["updated_at"] is None and out["updated_by"] is None
    assert out["can_edit"] is True
    assert agenda_absences.to_out(doc, VIEWER_OTHER)["can_edit"] is False
    assert agenda_absences.to_out(doc, VIEWER_RESP)["can_edit"] is True
    assert set(out) == {"id", "helper", "start_date", "end_date", "open_ended", "reason", "phase", "created_at",
                        "created_by", "updated_at", "updated_by", "can_edit"}


def test_absence_to_out_tolerates_incomplete_documents():
    out = agenda_absences.to_out({"id": "x", "start_date": "2026-10-01", "end_date": "2026-10-02"}, VIEWER_STAFF)
    assert out["helper"]["username"] == "Membre inconnu" and out["created_by"] is None and out["reason"] == ""
    assert out["created_at"] is None and out["can_edit"] is False
    # Horodatage BSON (naïf) : renvoyé en ISO UTC avec Z.
    out = agenda_absences.to_out(absence_doc("x", "2026-10-01", "2026-10-02", updated_at=datetime(2026, 10, 3, 9, 0)),
                                 VIEWER_STAFF)
    assert out["updated_at"] == "2026-10-03T09:00:00Z"


def test_legacy_view_uses_sentinel_and_never_writes_it():
    open_doc = absence_doc("a", "2026-10-01", None, open_ended=True)
    view = agenda_absences.legacy_view(open_doc)
    assert view["end_date"] == "9999-12-31" and view["open_ended"] is True
    assert open_doc["end_date"] is None
    closed = agenda_absences.legacy_view(absence_doc("b", "2026-10-01", "2026-10-02", open_ended=False))
    assert closed["end_date"] == "2026-10-02" and closed["open_ended"] is False
    assert set(closed) == {"id", "helper", "start_date", "end_date", "open_ended", "reason", "created_at"}
    # Ancien document sans `open_ended` ni fin.
    assert agenda_absences.legacy_view(absence_doc("c", "2026-10-01", None))["end_date"] == "9999-12-31"
    # Le contrat de l'ancien modèle de réponse est tenu.
    from models.staff import AbsenceEntry

    assert AbsenceEntry(**view).end_date == "9999-12-31"


def test_absence_overlap_query_includes_open_ended_and_cross_month():
    insert("absences", absence_doc("camille", "2026-10-05", "2026-10-10"))
    insert("absences", absence_doc("cross", "2026-10-30", "2026-11-02"))
    insert("absences", absence_doc("open", "2026-10-01", None, open_ended=True))
    insert("absences", absence_doc("legacy-open", "2026-09-01", None))
    insert("absences", absence_doc("later", "2026-12-01", "2026-12-03"))
    insert("absences", absence_doc("sentinel-free", "2026-10-12", "2026-10-13"))
    del_field = {"$unset": {"end_date": ""}}
    h.run(db.absences.update_one({"id": "legacy-open"}, del_field))

    found = h.run(db.absences.find(agenda_absences.overlap_query("2026-11-01", "2026-11-30"), {"_id": 0}).to_list(50))

    assert {doc["id"] for doc in found} == {"cross", "open", "legacy-open"}


def test_absence_validate_and_merge_messages_on_creation():
    merge = agenda_absences.validate_and_merge
    base = {"start_date": "2026-10-28", "end_date": "2026-11-02", "open_ended": False, "reason": ""}

    assert merge(None, base) == {"start_date": "2026-10-28", "end_date": "2026-11-02", "open_ended": False,
                                 "reason": ""}
    raises_http(lambda: merge(None, {**base, "open_ended": True}), 422,
                "Une absence sans date de fin ne peut pas avoir de date de fin.")
    raises_http(lambda: merge(None, {**base, "end_date": None}), 422,
                "Indiquez une date de fin ou cochez « Fin indéterminée ».")
    raises_http(lambda: merge(None, {**base, "end_date": "2026-10-27"}), 422,
                "La date de fin doit suivre la date de début.")
    raises_http(lambda: merge(None, {**base, "start_date": "2024-01-01", "end_date": "2024-01-02"}), 422,
                "Date de début hors limites.")
    raises_http(lambda: merge(None, {**base, "start_date": "2029-01-01", "end_date": "2029-01-02"}), 422,
                "Date de début hors limites.")
    raises_http(lambda: merge(None, {**base, "end_date": "2027-11-05"}), 422, "Une absence ne peut pas dépasser un an.")
    # Exactement un an : accepté ; sans fin : accepté.
    assert merge(None, {**base, "end_date": "2027-10-29"})["end_date"] == "2027-10-29"
    open_merged = merge(None, {**base, "end_date": None, "open_ended": True})
    assert open_merged["end_date"] is None and open_merged["open_ended"] is True
    raises_http(lambda: merge(None, {**base, "start_date": None}), 422, "Champ obligatoire : date de début.")


def test_absence_validate_and_merge_patch_semantics():
    merge = agenda_absences.validate_and_merge
    closed = absence_doc("a", "2026-10-20", "2026-10-30", open_ended=False, reason="Vacances")
    open_doc = absence_doc("b", "2026-10-20", None, open_ended=True)

    # `open_ended: true` efface la fin ; un `end_date` non nul remet `open_ended` à faux.
    assert merge(closed, {"open_ended": True}) == {"start_date": "2026-10-20", "end_date": None, "open_ended": True,
                                                   "reason": "Vacances"}
    assert merge(open_doc, {"end_date": "2026-11-02"}) == {"start_date": "2026-10-20", "end_date": "2026-11-02",
                                                           "open_ended": False, "reason": ""}
    # `end_date: null` seul sur une absence qui n'est pas sans fin : 422.
    raises_http(lambda: merge(closed, {"end_date": None}), 422, "Indiquez une date de fin ou cochez « Fin indéterminée ».")
    # `end_date: null` + `open_ended: true` : accepté.
    assert merge(closed, {"end_date": None, "open_ended": True})["open_ended"] is True
    # `open_ended: false` sans fin stockée : il faut une date.
    raises_http(lambda: merge(open_doc, {"open_ended": False}), 422,
                "Indiquez une date de fin ou cochez « Fin indéterminée ».")
    # Cohérence sur le document fusionné.
    raises_http(lambda: merge(closed, {"start_date": "2026-11-05"}), 422, "La date de fin doit suivre la date de début.")
    # `null` sur un champ obligatoire.
    raises_http(lambda: merge(closed, {"start_date": None}), 422, "Champ obligatoire : date de début.")
    raises_http(lambda: merge(closed, {"open_ended": None}), 422, "Champ obligatoire : fin indéterminée.")
    # Le motif seul ne touche à rien d'autre.
    assert merge(closed, {"reason": "Congé"})["end_date"] == "2026-10-30"
    assert merge(closed, {"reason": None})["reason"] == ""


def test_absence_bounds_only_checked_on_sent_date_fields():
    old = absence_doc("old", "2025-09-20", "2026-10-24", open_ended=False)
    merge = agenda_absences.validate_and_merge

    assert merge(old, {"reason": "Congé long"})["reason"] == "Congé long"
    raises_http(lambda: merge(old, {"start_date": "2025-09-21"}), 422, "Date de début hors limites.")
    # Une date récente, mais durée > 1 an : refus par la durée maximale.
    raises_http(lambda: merge(absence_doc("x", "2026-10-25", "2026-10-26"), {"end_date": "2027-12-31"}), 422,
                "Une absence ne peut pas dépasser un an.")


def test_create_absence_for_self_other_and_unknown():
    mine = h.run(agenda_absences.create({"start_date": "2026-10-28", "end_date": "2026-11-02", "reason": "Vacances"},
                                        H_STAFF, VIEWER_STAFF))
    assert mine["helper"]["id"] == STAFF and mine["created_by"]["id"] == STAFF
    assert mine["open_ended"] is False and mine["updated_at"] is None
    assert stored("absences", mine["id"])["end_date"] == "2026-11-02"

    open_one = h.run(agenda_absences.create({"start_date": "2026-10-22", "open_ended": True}, H_STAFF, VIEWER_STAFF))
    assert open_one["end_date"] is None and open_one["open_ended"] is True
    assert agenda_absences.to_out(open_one, VIEWER_STAFF)["phase"] == "en_cours"

    payload = {"start_date": "2026-10-28", "end_date": "2026-11-02", "helper_id": ANIM}
    raises_http(agenda_absences.create(payload, H_STAFF, VIEWER_STAFF), 403,
                "Seul un responsable peut déclarer l'absence d'un autre membre.")
    other = h.run(agenda_absences.create(payload, H_RESP, VIEWER_RESP))
    assert other["helper"]["id"] == ANIM and other["created_by"]["id"] == RESP
    assert set(other["helper"]) == {"id", "username", "display_name", "avatar_url"}
    raises_http(agenda_absences.create({**payload, "helper_id": UNKNOWN}, H_RESP, VIEWER_RESP), 404,
                "Membre introuvable parmi le staff.")
    # Aucune ligne de rappel pour une absence, jamais.
    assert h.run(db.agenda_reminders.count_documents({})) == 0


def test_create_absence_for_other_when_directory_is_down(monkeypatch):
    async def broken(self, role_id):
        raise OSError("réseau")

    monkeypatch.setattr(DiscordService, "fetch_helpers", broken)
    raises_http(agenda_absences.create({"start_date": "2026-10-28", "end_date": "2026-11-02", "helper_id": ANIM},
                                       H_RESP, VIEWER_RESP), 503, "Liste du staff indisponible, réessayez.")


def test_get_and_invalid_ids_are_404():
    insert("absences", absence_doc("old-2025", "2025-03-01", "2025-03-05"))
    assert h.run(agenda_absences.get("old-2025"))["id"] == "old-2025"
    for bad in ("a.b", "%20x", "x" * 65, "", "a/b"):
        raises_http(agenda_absences.get(bad), 404, "Absence introuvable.")
    raises_http(agenda_absences.get("inconnue"), 404, "Absence introuvable.")


def test_patch_absence_permissions_and_toggle():
    insert("absences", absence_doc("a1", "2026-10-20", "2026-10-30", open_ended=False))

    raises_http(agenda_absences.patch("a1", {"reason": "x"}, H_OTHER, VIEWER_OTHER), 403,
                "Seul l'auteur de l'absence ou un responsable peut la modifier.")
    assert stored("absences", "a1")["reason"] == ""

    out = h.run(agenda_absences.patch("a1", {"open_ended": True}, H_STAFF, VIEWER_STAFF))
    assert out["end_date"] is None and out["open_ended"] is True
    assert stored("absences", "a1")["updated_by"]["id"] == STAFF
    assert agenda_absences.to_out(out, VIEWER_STAFF)["phase"] == "en_cours"

    out = h.run(agenda_absences.patch("a1", {"end_date": "2026-11-02"}, H_RESP, VIEWER_RESP))
    assert out["open_ended"] is False and out["end_date"] == "2026-11-02"
    assert stored("absences", "a1")["updated_by"]["id"] == RESP

    raises_http(agenda_absences.patch("a1", {"end_date": None}, H_STAFF, VIEWER_STAFF), 422,
                "Indiquez une date de fin ou cochez « Fin indéterminée ».")
    assert stored("absences", "a1")["end_date"] == "2026-11-02"
    raises_http(agenda_absences.patch("inconnue", {"reason": "x"}, H_STAFF, VIEWER_STAFF), 404, "Absence introuvable.")
    # `helper_id` n'est pas modifiable.
    with pytest.raises(Exception):
        h.run(agenda_absences.patch("a1", {"helper_id": ANIM}, H_RESP, VIEWER_RESP))


def test_patch_with_old_absence_changes_reason_only():
    insert("absences", absence_doc("old", "2025-09-20", "2026-10-24", open_ended=False))

    out = h.run(agenda_absences.patch("old", {"reason": "Congé long"}, H_STAFF, VIEWER_STAFF))

    assert out["reason"] == "Congé long" and out["start_date"] == "2025-09-20" and out["end_date"] == "2026-10-24"
    raises_http(agenda_absences.patch("old", {"start_date": "2025-09-21"}, H_STAFF, VIEWER_STAFF), 422,
                "Date de début hors limites.")


def test_return_sets_end_date_to_the_day_before():
    insert("absences", absence_doc("open", "2026-10-15", None, open_ended=True))

    out = h.run(agenda_absences.mark_return("open", None, H_STAFF, VIEWER_STAFF))

    assert out["end_date"] == "2026-10-24" and out["open_ended"] is False
    assert stored("absences", "open")["end_date"] == "2026-10-24"
    assert agenda_absences.to_out(out, VIEWER_STAFF)["phase"] == "passee"


def test_return_with_explicit_date_and_limits():
    insert("absences", absence_doc("future", "2026-10-26", None, open_ended=True))
    raises_http(agenda_absences.mark_return("future", AbsenceReturn(return_date="2026-10-25"), H_STAFF, VIEWER_STAFF),
                422, "L'absence n'a pas encore commencé : supprimez-la plutôt.")
    assert stored("absences", "future")["open_ended"] is True

    insert("absences", absence_doc("a", "2026-10-10", None, open_ended=True))
    raises_http(agenda_absences.mark_return("a", {"return_date": "2026-10-27"}, H_STAFF, VIEWER_STAFF), 422,
                "La date de retour ne peut pas être dans le futur.")
    # Demain est permis (retour le lendemain) ; la fin est alors aujourd'hui.
    out = h.run(agenda_absences.mark_return("a", {"return_date": "2026-10-26"}, H_STAFF, VIEWER_STAFF))
    assert out["end_date"] == "2026-10-25"
    # Le jour du début : pas encore commencée.
    insert("absences", absence_doc("b", "2026-10-10", None, open_ended=True))
    raises_http(agenda_absences.mark_return("b", {"return_date": "2026-10-10"}, H_STAFF, VIEWER_STAFF), 422,
                "L'absence n'a pas encore commencé : supprimez-la plutôt.")


def test_return_exempt_from_one_year_cap_and_only_shortens():
    insert("absences", absence_doc("long", "2025-09-20", None, open_ended=True))
    out = h.run(agenda_absences.mark_return("long", None, H_STAFF, VIEWER_STAFF))
    assert out["end_date"] == "2026-10-24"

    # Retour anticipé d'une absence à date de fin.
    insert("absences", absence_doc("early", "2026-10-20", "2026-11-10", open_ended=False))
    assert h.run(agenda_absences.mark_return("early", None, H_STAFF, VIEWER_STAFF))["end_date"] == "2026-10-24"
    # Une absence déjà terminée plus tôt garde sa fin.
    insert("absences", absence_doc("done", "2026-10-01", "2026-10-05", open_ended=False))
    assert h.run(agenda_absences.mark_return("done", None, H_STAFF, VIEWER_STAFF))["end_date"] == "2026-10-05"


def test_return_and_delete_by_other_staff_forbidden():
    insert("absences", absence_doc("a", "2026-10-10", None, open_ended=True))
    raises_http(agenda_absences.mark_return("a", None, H_OTHER, VIEWER_OTHER), 403,
                "Seul l'auteur de l'absence ou un responsable peut la modifier.")
    assert stored("absences", "a")["open_ended"] is True
    raises_http(agenda_absences.delete("a", H_OTHER, VIEWER_OTHER), 403,
                "Seul l'auteur de l'absence ou un responsable peut la supprimer.")
    h.run(agenda_absences.delete("a", H_RESP, VIEWER_RESP))
    assert stored("absences", "a") is None
    raises_http(agenda_absences.delete("a", H_RESP, VIEWER_RESP), 404, "Absence introuvable.")


class MemberDirectory:
    """Remplace DiscordService.fetch_member : compte les appels et peut échouer."""

    def __init__(self, monkeypatch):
        self.calls: list[str] = []
        self.error: Exception | None = None

        async def fetch_member(service, member_id):
            self.calls.append(member_id)
            if self.error is not None:
                raise self.error
            if member_id == GONE:
                raise HTTPException(status_code=404, detail="Ressource Discord introuvable.")
            return discord_service.DiscordMember(
                id=member_id, username=f"nouveau-{member_id[-2:]}", display_name="Nom frais", avatar_url="https://a/b.png",
            )

        monkeypatch.setattr(DiscordService, "fetch_member", fetch_member)


def test_refresh_identities_is_throttled_per_member(monkeypatch):
    members = MemberDirectory(monkeypatch)
    insert("absences", absence_doc("a1", "2026-10-20", "2026-10-30", helper_id=STAFF))
    insert("absences", absence_doc("a2", "2026-11-05", "2026-11-06", helper_id=STAFF))
    insert("absences", absence_doc("a3", "2026-10-20", "2026-10-30", helper_id=GONE))

    def read():
        return h.run(db.absences.find({}, {"_id": 0}).sort("start_date", 1).to_list(50))

    docs = h.run(agenda_absences.refresh_identities(read()))
    assert sorted(members.calls) == sorted([STAFF, GONE])
    by_id = {doc["id"]: doc for doc in docs}
    assert by_id["a1"]["helper"]["display_name"] == "Nom frais"
    # Membre parti (404) : horodaté pour ne pas être réessayé, identité inchangée.
    assert by_id["a3"]["helper"]["username"] == "membre"
    assert stored("absences", "a2")["helper"]["username"] == f"nouveau-{STAFF[-2:]}"
    assert stored("absences", "a3")["helper_refreshed_at"] is not None

    h.run(agenda_absences.refresh_identities(read()))
    assert len(members.calls) == 2

    set_clock(monkeypatch, NOW + timedelta(hours=13))
    h.run(agenda_absences.refresh_identities(read()))
    assert len(members.calls) == 4


def test_refresh_identities_ignores_errors_and_missing_bot_config(monkeypatch):
    members = MemberDirectory(monkeypatch)
    insert("absences", absence_doc("a1", "2026-10-20", "2026-10-30", helper_id=STAFF))
    members.error = HTTPException(status_code=502, detail="Discord en panne")

    docs = h.run(agenda_absences.refresh_identities(h.run(db.absences.find({}, {"_id": 0}).to_list(10))))
    assert docs[0]["helper"]["username"] == "membre" and "helper_refreshed_at" not in docs[0]
    assert "helper_refreshed_at" not in stored("absences", "a1")

    members.error = OSError("réseau coupé")
    h.run(agenda_absences.refresh_identities(h.run(db.absences.find({}, {"_id": 0}).to_list(10))))
    assert "helper_refreshed_at" not in stored("absences", "a1")

    def broken_constructor():
        raise HTTPException(status_code=503, detail="Bot non configuré")

    calls = len(members.calls)
    monkeypatch.setattr(discord_service, "DiscordService", broken_constructor)
    docs = h.run(agenda_absences.refresh_identities(h.run(db.absences.find({}, {"_id": 0}).to_list(10))))
    assert len(docs) == 1 and len(members.calls) == calls


# ---------------------------------------------------------------------------
# Entrées
# ---------------------------------------------------------------------------

def entry_payload(**overrides) -> dict:
    payload = {"type": "evenement", "title": "Soirée jeux", "start_date": "2026-10-29", "all_day": False,
               "start_time": "20:30", "end_time": "22:30", "location": "Vocal Événements"}
    payload.update(overrides)
    return payload


def make_entry(helper=H_STAFF, viewer=VIEWER_STAFF, **overrides) -> dict:
    return h.run(agenda_entries.create(entry_payload(**overrides), helper, viewer))


def test_entry_validation_messages():
    create = agenda_entries.create

    raises_http(create(entry_payload(type="autre"), H_STAFF, VIEWER_STAFF), 422, "Indiquez un libellé pour ce type.")
    raises_http(create(entry_payload(type="autre", custom_label="   "), H_STAFF, VIEWER_STAFF), 422,
                "Indiquez un libellé pour ce type.")
    raises_http(create(entry_payload(type="echeance", all_day=True, start_time=None, end_time=None,
                                     end_date="2026-10-30"), H_STAFF, VIEWER_STAFF), 422,
                "Une échéance ou un rappel porte sur un seul jour.")
    raises_http(create(entry_payload(start_time=None, end_time=None), H_STAFF, VIEWER_STAFF), 422,
                "Indiquez une heure de début.")
    raises_http(create(entry_payload(end_time="20:30"), H_STAFF, VIEWER_STAFF), 422,
                "L'heure de fin doit suivre l'heure de début.")
    raises_http(create(entry_payload(end_time="19:00"), H_STAFF, VIEWER_STAFF), 422,
                "L'heure de fin doit suivre l'heure de début.")
    raises_http(create(entry_payload(all_day=True, start_time="10:00", end_time=None), H_STAFF, VIEWER_STAFF), 422,
                "Une entrée sur la journée n'a pas d'heure.")
    raises_http(create(entry_payload(all_day=True, start_time=None, end_time=None, end_date="2026-10-28"),
                       H_STAFF, VIEWER_STAFF), 422, "La date de fin doit suivre la date de début.")
    raises_http(create(entry_payload(all_day=True, start_time=None, end_time=None, end_date="2027-02-01"),
                       H_STAFF, VIEWER_STAFF), 422, "Une entrée ne peut pas dépasser 3 mois.")
    raises_http(create(entry_payload(start_date="2024-01-01"), H_STAFF, VIEWER_STAFF), 422, "Date hors limites.")
    raises_http(create(entry_payload(start_date="2029-12-31"), H_STAFF, VIEWER_STAFF), 422, "Date hors limites.")
    assert h.run(db.agenda_entries.count_documents({})) == 0


def test_entry_create_defaults_and_normalisation():
    entry = make_entry(all_day=True, start_time=None, end_time=None, title="  Clôture  ", type="echeance",
                       custom_label="ignoré")
    assert entry["title"] == "Clôture" and entry["custom_label"] is None
    assert entry["start_time"] is None and entry["end_time"] is None and entry["end_date"] is None
    assert entry["reminders"] == {"enabled": True, "offsets": ["J-7", "J-2", "J-1", "H-1"], "ping_role": False}
    assert entry["participants"] == [] and entry["created_by"]["id"] == STAFF and entry["updated_at"] is None

    other = make_entry(type="autre", custom_label="Formation", all_day=True, start_time=None, end_time=None,
                       end_date="2026-10-29")
    assert other["custom_label"] == "Formation"
    # Fin égale au début : même jour, enregistrée comme `null`.
    assert other["end_date"] is None

    multi = make_entry(all_day=True, start_time=None, end_time=None, end_date="2026-11-02")
    assert multi["end_date"] == "2026-11-02"
    # Fin sur un autre jour : l'heure de fin peut précéder l'heure de début.
    night = make_entry(end_date="2026-10-30", start_time="22:00", end_time="02:00")
    assert night["end_time"] == "02:00"

    out = agenda_entries.to_out(entry, VIEWER_STAFF)
    assert out["type"] == "echeance" and out["can_edit"] is True and out["reminders"]["schedule"] == []
    assert agenda_entries.to_out(entry, VIEWER_OTHER)["can_edit"] is False
    assert agenda_entries.to_out(entry, VIEWER_RESP)["can_edit"] is True


def test_entry_participants_resolved_and_validated():
    entry = make_entry(participant_ids=[ANIM, STAFF, ANIM])
    assert [p["id"] for p in entry["participants"]] == [ANIM, STAFF]
    assert set(entry["participants"][0]) == {"id", "username", "display_name", "avatar_url"}

    raises_http(agenda_entries.create(entry_payload(participant_ids=[UNKNOWN]), H_STAFF, VIEWER_STAFF), 422,
                f"Participant inconnu : {UNKNOWN}.")

    # PATCH : un participant parti reste ; seul un nouvel id est vérifié.
    h.run(db.agenda_entries.update_one({"id": entry["id"]}, {"$push": {"participants": person(GONE, "parti")}}))
    out = h.run(agenda_entries.patch(entry["id"], {"participant_ids": [GONE, STAFF]}, H_STAFF, VIEWER_STAFF))
    assert [p["id"] for p in out["participants"]] == [GONE, STAFF]
    assert out["participants"][0]["username"] == "parti"
    raises_http(agenda_entries.patch(entry["id"], {"participant_ids": [UNKNOWN]}, H_STAFF, VIEWER_STAFF), 422,
                f"Participant inconnu : {UNKNOWN}.")
    assert h.run(agenda_entries.patch(entry["id"], {"participant_ids": None}, H_STAFF, VIEWER_STAFF))["participants"] == []


def test_ping_role_requires_responsable_and_is_kept():
    raises_http(agenda_entries.create(entry_payload(reminders={"enabled": True, "ping_role": True}), H_STAFF,
                                      VIEWER_STAFF), 403, "Seul un responsable peut activer la mention du rôle.")
    entry = make_entry(helper=H_RESP, viewer=VIEWER_RESP, reminders={"enabled": True, "ping_role": True})
    assert entry["reminders"]["ping_role"] is True

    # Le staff qui modifie le titre d'une entrée où la mention est active la conserve.
    h.run(db.agenda_entries.update_one({"id": entry["id"]}, {"$set": {"created_by": person(STAFF)}}))
    out = h.run(agenda_entries.patch(entry["id"], {"title": "Autre titre"}, H_STAFF, VIEWER_STAFF))
    assert out["title"] == "Autre titre" and out["reminders"]["ping_role"] is True
    assert stored("agenda_entries", entry["id"])["reminders"]["ping_role"] is True
    # Renvoyer la même valeur est permis ; l'activer quand elle est éteinte non.
    out = h.run(agenda_entries.patch(entry["id"], {"reminders": {"ping_role": True}}, H_STAFF, VIEWER_STAFF))
    assert out["reminders"]["ping_role"] is True
    plain = make_entry()
    raises_http(agenda_entries.patch(plain["id"], {"reminders": {"ping_role": True}}, H_STAFF, VIEWER_STAFF), 403,
                "Seul un responsable peut activer la mention du rôle.")
    assert stored("agenda_entries", plain["id"])["reminders"]["ping_role"] is False


def test_entry_permissions():
    entry = make_entry()
    raises_http(agenda_entries.patch(entry["id"], {"title": "x"}, H_OTHER, VIEWER_OTHER), 403,
                "Seul l'auteur ou un responsable peut modifier cette entrée.")
    raises_http(agenda_entries.delete(entry["id"], H_OTHER, VIEWER_OTHER), 403,
                "Seul l'auteur ou un responsable peut supprimer cette entrée.")
    assert stored("agenda_entries", entry["id"])["title"] == "Soirée jeux"
    assert h.run(agenda_entries.patch(entry["id"], {"title": "Auteur"}, H_STAFF, VIEWER_STAFF))["title"] == "Auteur"
    assert h.run(agenda_entries.patch(entry["id"], {"title": "Resp"}, H_RESP, VIEWER_RESP))["title"] == "Resp"
    assert stored("agenda_entries", entry["id"])["updated_by"]["id"] == RESP
    h.run(agenda_entries.delete(entry["id"], H_RESP, VIEWER_RESP))
    raises_http(agenda_entries.get(entry["id"]), 404, "Entrée introuvable.")
    for bad in ("a.b", "%20x", "x" * 65):
        raises_http(agenda_entries.get(bad), 404, "Entrée introuvable.")


def test_entry_patch_null_semantics():
    entry = make_entry()
    out = h.run(agenda_entries.patch(entry["id"], {"all_day": True}, H_STAFF, VIEWER_STAFF))
    assert out["all_day"] is True and out["start_time"] is None and out["end_time"] is None
    assert stored("agenda_entries", entry["id"])["start_time"] is None

    timed = make_entry()
    raises_http(agenda_entries.patch(timed["id"], {"all_day": True, "start_time": "20:30"}, H_STAFF, VIEWER_STAFF), 422,
                "Une entrée sur la journée n'a pas d'heure.")
    out = h.run(agenda_entries.patch(timed["id"], {"all_day": True, "start_time": None, "end_time": None}, H_STAFF,
                                     VIEWER_STAFF))
    assert out["start_time"] is None
    raises_http(agenda_entries.patch(timed["id"], {"title": None}, H_STAFF, VIEWER_STAFF), 422,
                "Champ obligatoire : titre.")
    raises_http(agenda_entries.patch(timed["id"], {"type": None}, H_STAFF, VIEWER_STAFF), 422,
                "Champ obligatoire : type.")
    raises_http(agenda_entries.patch(timed["id"], {"start_date": None}, H_STAFF, VIEWER_STAFF), 422,
                "Champ obligatoire : date de début.")
    raises_http(agenda_entries.patch(timed["id"], {"reminders": None}, H_STAFF, VIEWER_STAFF), 422,
                "Champ obligatoire : rappels.")
    raises_http(agenda_entries.patch(timed["id"], {"all_day": None}, H_STAFF, VIEWER_STAFF), 422,
                "Champ obligatoire : toute la journée.")

    # Passer à « horaire » exige une heure de début ; `null` efface une fin ; `location`/`description` null = "".
    raises_http(agenda_entries.patch(timed["id"], {"all_day": False}, H_STAFF, VIEWER_STAFF), 422,
                "Indiquez une heure de début.")
    out = h.run(agenda_entries.patch(timed["id"], {"all_day": False, "start_time": "09:00"}, H_STAFF, VIEWER_STAFF))
    assert out["start_time"] == "09:00" and out["end_time"] is None
    out = h.run(agenda_entries.patch(timed["id"], {"location": None, "description": None, "end_date": None}, H_STAFF,
                                     VIEWER_STAFF))
    assert out["location"] == "" and out["description"] == "" and out["end_date"] is None
    # `type: autre` demande un libellé ; changer pour un autre type l'efface.
    raises_http(agenda_entries.patch(timed["id"], {"type": "autre"}, H_STAFF, VIEWER_STAFF), 422,
                "Indiquez un libellé pour ce type.")
    out = h.run(agenda_entries.patch(timed["id"], {"type": "autre", "custom_label": "Formation"}, H_STAFF, VIEWER_STAFF))
    assert out["custom_label"] == "Formation"
    out = h.run(agenda_entries.patch(timed["id"], {"type": "permanence"}, H_STAFF, VIEWER_STAFF))
    assert out["custom_label"] is None


def test_entry_patch_bounds_only_on_sent_fields_and_consistency():
    insert("agenda_entries", {"id": "old", "type": "evenement", "custom_label": None, "title": "Ancien", "description": "",
                              "all_day": True, "start_date": "2025-03-01", "end_date": None, "start_time": None,
                              "end_time": None, "location": "", "participants": [],
                              "reminders": {"enabled": False, "offsets": [], "ping_role": False},
                              "created_by": person(STAFF), "created_at": "2025-03-01T10:00:00+00:00",
                              "updated_by": None, "updated_at": None})

    assert h.run(agenda_entries.patch("old", {"title": "Nouveau titre"}, H_STAFF, VIEWER_STAFF))["title"] == "Nouveau titre"
    raises_http(agenda_entries.patch("old", {"start_date": "2025-03-02"}, H_STAFF, VIEWER_STAFF), 422, "Date hors limites.")

    entry = make_entry(all_day=True, start_time=None, end_time=None)
    raises_http(agenda_entries.patch(entry["id"], {"end_date": "2026-10-20"}, H_STAFF, VIEWER_STAFF), 422,
                "La date de fin doit suivre la date de début.")
    raises_http(agenda_entries.patch(entry["id"], {"type": "rappel", "end_date": "2026-10-31"}, H_STAFF, VIEWER_STAFF),
                422, "Une échéance ou un rappel porte sur un seul jour.")
    raises_http(agenda_entries.patch(entry["id"], {"end_date": "2027-03-01"}, H_STAFF, VIEWER_STAFF), 422,
                "Une entrée ne peut pas dépasser 3 mois.")
    # Passer en échéance une entrée déjà sur plusieurs jours est refusé même sans toucher aux dates.
    multi = make_entry(all_day=True, start_time=None, end_time=None, end_date="2026-10-31")
    raises_http(agenda_entries.patch(multi["id"], {"type": "echeance"}, H_STAFF, VIEWER_STAFF), 422,
                "Une échéance ou un rappel porte sur un seul jour.")


def test_entry_overlap_single_day_is_not_open_ended():
    def doc(entry_id, start, end):
        return {"id": entry_id, "type": "evenement", "title": entry_id, "all_day": True, "start_date": start,
                "end_date": end}

    insert("agenda_entries", doc("single-oct", "2026-10-14", None))
    insert("agenda_entries", doc("multi", "2026-10-30", "2026-11-02"))
    insert("agenda_entries", doc("single-nov", "2026-11-10", None))
    insert("agenda_entries", doc("before", "2026-10-01", "2026-10-03"))
    insert("agenda_entries", doc("after", "2026-12-01", None))

    found = h.run(db.agenda_entries.find(agenda_entries.overlap_query("2026-11-01", "2026-11-30"), {"_id": 0}).to_list(20))
    assert {entry["id"] for entry in found} == {"multi", "single-nov"}
    # Le jour même et les bornes incluses.
    found = h.run(db.agenda_entries.find(agenda_entries.overlap_query("2026-10-14", "2026-10-14"), {"_id": 0}).to_list(20))
    assert {entry["id"] for entry in found} == {"single-oct"}
    found = h.run(db.agenda_entries.find(agenda_entries.overlap_query("2026-11-02", "2026-11-02"), {"_id": 0}).to_list(20))
    assert {entry["id"] for entry in found} == {"multi"}


def test_reminder_config_helpers_with_legacy_values():
    assert agenda_entries.stored_reminders(None) == {"enabled": False, "offsets": [], "ping_role": False}
    assert agenda_entries.stored_reminders({"enabled": True, "offsets": ["H-1", "J-7", "bad", "J-7"], "ping_role": True}) == {
        "enabled": True, "offsets": ["J-7", "H-1"], "ping_role": True}
    assert agenda_entries.stored_reminders({"enabled": True, "offsets": []})["enabled"] is False

    from models.staff import ReminderConfig

    legacy = {"enabled": False, "offsets": [], "ping_role": False}
    enabled = agenda_entries.merge_reminders(legacy, ReminderConfig.model_validate({"enabled": True}))
    assert enabled == {"enabled": True, "offsets": ["J-7", "J-2", "J-1", "H-1"], "ping_role": False}
    kept = {"enabled": True, "offsets": ["J-1"], "ping_role": True}
    assert agenda_entries.merge_reminders(kept, ReminderConfig.model_validate({"enabled": False})) == {
        "enabled": False, "offsets": ["J-1"], "ping_role": True}
    assert agenda_entries.merge_reminders(kept, ReminderConfig.model_validate({"offsets": ["H-1"]}))["offsets"] == ["H-1"]
    assert agenda_entries.merge_reminders(kept, ReminderConfig.model_validate({"offsets": []}))["enabled"] is False
    assert agenda_entries.merge_reminders(kept, None) == kept

    info = agenda_entries.reminder_info(kept, [{"offset": "J-1", "due_at": None, "status": "pending"}])
    assert info["schedule"] == [{"offset": "J-1", "due_at": None, "status": "pending"}]
    assert agenda_entries.reminder_info(legacy, [{"offset": "J-1"}])["schedule"] == []


def test_entry_to_out_survives_damaged_documents():
    out = agenda_entries.to_out({"id": "x", "type": "inconnu", "title": None, "start_date": "2026-10-29",
                                 "participants": "n'importe quoi", "start_time": "25:99", "all_day": False}, VIEWER_STAFF)
    assert out["type"] == "autre" and out["custom_label"] == "Autre" and out["title"] == ""
    assert out["participants"] == [] and out["start_time"] is None and out["created_by"] is None


# ---------------------------------------------------------------------------
# Réunions : contenu BlockNote
# ---------------------------------------------------------------------------

def text(value: str, **styles) -> dict:
    return {"type": "text", "text": value, "styles": styles}


def paragraph(*content, children=None, **extra) -> dict:
    block = {"id": "b1", "type": "paragraph", "props": {}, "content": list(content), "children": children or []}
    block.update(extra)
    return block


def link(href, *content) -> dict:
    return {"type": "link", "href": href, "content": list(content)}


def dumps(blocks) -> str:
    return json.dumps(blocks, ensure_ascii=False)


def sanitized(blocks) -> list:
    raw, _text, _words = agenda_meetings.prepare_content(dumps(blocks), allow_text=False)
    return json.loads(raw) if raw else []


def first_inline(blocks) -> list:
    return blocks[0]["content"]


def test_prepare_content_basics():
    assert agenda_meetings.prepare_content("", allow_text=False) == ("", "", 0)
    assert agenda_meetings.prepare_content("   ", allow_text=False) == ("", "", 0)
    assert agenda_meetings.prepare_content(None, allow_text=False) == ("", "", 0)
    assert agenda_meetings.prepare_content("[]", allow_text=False) == ("", "", 0)

    raw, content_text, words = agenda_meetings.prepare_content(
        dumps([paragraph(text("Bonjour tout le monde")), paragraph(text("Deuxième ligne"))]), allow_text=False)
    assert content_text == "Bonjour tout le monde\nDeuxième ligne" and words == 6
    assert json.loads(raw)[0]["content"][0]["text"] == "Bonjour tout le monde"
    assert " " not in raw.replace("Bonjour tout le monde", "").replace("Deuxième ligne", "")  # sérialisation compacte
    assert "è" in raw  # pas d'échappement ASCII


def test_prepare_content_rejects_non_lists_for_the_new_api_only():
    for raw in ('"bonjour"', "bonjour", '{"a": 1}', "42", "null", "{"):
        raises_http(lambda raw=raw: agenda_meetings.prepare_content(raw, allow_text=False), 422, "Contenu illisible.")
    raises_http(lambda: agenda_meetings.prepare_content(["pas", "une", "chaîne"], allow_text=False), 422,
                "Contenu illisible.")

    raw, content_text, words = agenda_meetings.prepare_content("Ancien compte-rendu en texte brut", allow_text=True)
    assert raw == "Ancien compte-rendu en texte brut" and content_text == raw and words == 5
    # Texte brut qui ressemble à du JSON mais n'est pas une liste : gardé tel quel côté legacy.
    assert agenda_meetings.prepare_content('{"a": 1}', allow_text=True)[0] == '{"a": 1}'


def test_unreadable_nested_content_is_422_not_500():
    nested = "[" * 20000 + "]" * 20000
    raises_http(lambda: agenda_meetings.prepare_content(nested, allow_text=False), 422, "Contenu illisible.")
    raw, content_text, words = agenda_meetings.prepare_content(nested, allow_text=True)
    assert raw == nested and words == 1

    # Éléments qui ne sont pas des objets : retirés.
    kept = sanitized([1, "a", None, [], paragraph(text("Gardé"))])
    assert [block["content"][0]["text"] for block in kept] == ["Gardé"]
    assert agenda_meetings.prepare_content(dumps([1, "a"]), allow_text=False) == ("", "", 0)

    # Enfants imbriqués sur 30 niveaux : coupés à 20.
    block = paragraph(text("fond"))
    for _ in range(29):
        block = paragraph(text("niveau"), children=[block])
    levels, cursor = 1, sanitized([block])[0]
    while cursor.get("children"):
        cursor = cursor["children"][0]
        levels += 1
    assert levels == 20 and cursor["children"] == []

    # Même profondeur pour l'extraction de texte.
    assert agenda_meetings.blocks_to_text([block]).count("niveau") <= 20


def test_legacy_content_with_oversized_nesting_in_json_objects():
    deep = '{"a":' * 5000 + "1" + "}" * 5000
    raises_http(lambda: agenda_meetings.prepare_content(deep, allow_text=False), 422, "Contenu illisible.")
    derived = agenda_meetings.derived_fields({"title": "T", "content_markdown": deep})
    assert derived["content_text"] == "" and derived["word_count"] == 0 and "t" in derived["search_text"]


def test_sanitize_removes_dangerous_links_but_keeps_text():
    blocks = sanitized([paragraph(
        link("javascript:alert(1)", text("piège")),
        text(" - "),
        link("  JaVaScRiPt:x", text("casse")),
        text(" - "),
        link("https://exemple.fr/page", text("web")),
        link("HTTP://EXEMPLE.FR", text("majuscules")),
        link("mailto:a@b.fr", text("courriel")),
        link("MAILTO:a@b.fr", text("courriel2")),
        link("/staff/calendrier", text("site")),
        link("data:text/html,<script>", text("data")),
        link("vbscript:x", text("vb")),
    )])
    inline = first_inline(blocks)
    hrefs = [item["href"] for item in inline if item["type"] == "link"]
    assert hrefs == ["https://exemple.fr/page", "HTTP://EXEMPLE.FR", "mailto:a@b.fr", "MAILTO:a@b.fr", "/staff/calendrier"]
    joined = "".join(item["text"] for item in inline if item["type"] == "text")
    assert "piège" in joined and "casse" in joined and "data" in joined and "vb" in joined
    assert "javascript" not in json.dumps(inline).lower()


def test_sanitize_rejects_external_lookalikes():
    blocks = sanitized([paragraph(
        link("//evil.example", text("a")),
        link("/\\evil.example", text("b")),
        link("http:\\\\evil", text("c")),
        link("java\nscript:x", text("d")),
        link("https://ok.fr\n", text("e")),
        link("https://ok.fr/\tx", text("f")),
        link("", text("g")),
        link(None, text("h")),
        link(12, text("i")),
        link("tel:+33123456789", text("j")),
    )])
    inline = first_inline(blocks)
    assert [item for item in inline if item["type"] == "link"] == [
        {"type": "link", "href": "https://ok.fr", "content": [text("e")]},
    ]
    assert "".join(item["text"] for item in inline if item["type"] == "text") == "abcdfghij"


def test_sanitize_media_urls():
    uuid = "123e4567-e89b-12d3-a456-426614174000"
    image = lambda url: {"id": "i", "type": "image", "props": {"url": url, "caption": "", "previewWidth": 512}}  # noqa: E731
    blocks = sanitized([
        image(f"/api/staff/meetings/images/{uuid}.png"),
        image(f"https://api.loasis.app/api/staff/meetings/images/{uuid}.png"),
        image("javascript:alert(1)"),
        image("/api/staff/meetings/images/../../etc/passwd"),
        image("/api/staff/meetings/images/x.png"),
        image("http://tracker.example/p.gif"),
        image("//tracker.example/p.gif"),
        image(f"/api/staff/meetings/images/{uuid}.png\n"),
        image(12),
        {"id": "v", "type": "video", "props": {"url": "data:video/mp4;base64,AAAA"}},
        {"id": "a", "type": "audio", "props": {"url": "https://cdn.exemple.fr/a.mp3"}},
    ])
    urls = [block["props"]["url"] for block in blocks]
    assert urls == [
        f"/api/staff/meetings/images/{uuid}.png",
        f"https://api.loasis.app/api/staff/meetings/images/{uuid}.png",
        "", "", "", "", "", f"/api/staff/meetings/images/{uuid}.png", "", "", "https://cdn.exemple.fr/a.mp3",
    ]
    assert blocks[0]["props"]["previewWidth"] == 512


def test_sanitize_tables_nested_objects_and_unknown_inline():
    table = {
        "id": "t", "type": "table",
        "content": {"type": "tableContent", "columnWidths": [100, None, "x"], "rows": [
            {"cells": [[text("A1"), link("javascript:x", text("B1"))], {"type": "tableCell", "content": [text("C1")]}, 5]},
            "pas une ligne",
        ]},
    }
    clean = sanitized([table, paragraph("texte brut", {"type": "mention", "text": "@qui"}, {"type": "x", "content": [text("in")]},
                                        {"type": "text", "text": 5})])
    cells = clean[0]["content"]["rows"][0]["cells"]
    assert clean[0]["content"]["columnWidths"] == [100, None, None]
    assert len(clean[0]["content"]["rows"]) == 1 and len(cells) == 3
    assert cells[0][1] == text("B1") and cells[2] == []
    assert cells[1]["content"][0]["text"] == "C1"
    inline = clean[1]["content"]
    assert inline[0] == "texte brut"
    assert [item["text"] for item in inline[1:]] == ["@qui", "in"]
    # Propriétés imbriquées retirées, contenu inattendu remplacé par une liste vide.
    odd = sanitized([{"type": "paragraph", "props": {"a": {"b": 1}, "level": 2}, "content": 42, "children": "x", "extra": [1]}])
    assert odd == [{"type": "paragraph", "props": {"level": 2}, "content": [], "children": []}]


def test_blocks_to_text_reads_links_tables_and_children():
    blocks = [
        paragraph(text("Début "), link("https://a.fr", text("lien"), text(" suite"))),
        {"type": "table", "content": {"type": "tableContent", "rows": [
            {"cells": [[text("A1")], {"type": "tableCell", "content": [text("B1")]}]},
            {"cells": [[text("A2")], [text("B2")]]},
        ]}},
        {"type": "heading", "content": "Titre en chaîne", "children": [paragraph(text("Enfant"))]},
        {"type": "image", "props": {"url": ""}},
        "intrus",
        paragraph(text("   ")),
    ]
    assert agenda_meetings.blocks_to_text(blocks) == "Début lien suite\nA1\nB1\nA2\nB2\nTitre en chaîne\nEnfant"
    assert agenda_meetings.blocks_to_text("pas une liste") == ""
    assert len(agenda_meetings.blocks_to_text([paragraph(text("x" * 150000))])) == 100000


def test_search_normalisation_and_derived_fields():
    assert agenda_meetings.normalize_search("  Préparation   de l'ÉVÉNEMENT d'hiver ") == "preparation de l'evenement d'hiver"
    assert agenda_meetings.normalize_search("Ça Été Œuvre") == "ca ete œuvre"
    assert agenda_meetings.normalize_search(None) == ""

    doc = {"title": "Préparation de l'événement", "location": "Vocal Staff", "agenda": "1. Tour de table\n2. Divers",
           "decisions": [{"id": "d1", "text": "Passer à 2 personnes"}],
           "action_items": [{"id": "x1", "text": "Mettre à jour le Planning"}],
           "content_markdown": dumps([paragraph(text("Compte-rendu détaillé de la réunion"))])}
    derived = agenda_meetings.derived_fields(doc)
    assert derived["content_text"] == "Compte-rendu détaillé de la réunion"
    assert derived["word_count"] == 5 and derived["excerpt"] == derived["content_text"]
    for expected in ("evenement", "vocal staff", "tour de table", "divers", "2 personnes", "planning", "detaille"):
        assert expected in derived["search_text"]
    assert set(derived) == {"content_text", "search_text", "word_count", "excerpt"}

    long_doc = {"title": "T", "content_markdown": dumps([paragraph(text("mot " * 500))])}
    excerpt = agenda_meetings.derived_fields(long_doc)["excerpt"]
    assert len(excerpt) <= 220 and excerpt.endswith("…")
    assert len(agenda_meetings.derived_fields({"title": "T" * 30000})["search_text"]) == 20000


def test_derived_fields_for_unreadable_or_odd_content_never_raise():
    for bad in ("[" * 20000 + "]" * 20000, 12, ["liste"], {"objet": 1}, None):
        derived = agenda_meetings.derived_fields({"title": "Titre", "agenda": "1. Point", "content_markdown": bad})
        assert "titre" in derived["search_text"] and "point" in derived["search_text"]
    assert agenda_meetings.derived_fields({"title": "T", "content_markdown": 12})["content_text"] == ""
    # Texte brut d'un ancien compte-rendu : repris tel quel.
    legacy = agenda_meetings.derived_fields({"title": "T", "content_markdown": "Texte brut de l'ancien temps"})
    assert legacy["content_text"] == "Texte brut de l'ancien temps" and legacy["word_count"] == 5


# ---------------------------------------------------------------------------
# Réunions : lecture tolérante, phases
# ---------------------------------------------------------------------------

def legacy_meeting(meeting_id="legacy-1", **overrides) -> dict:
    doc = {"id": meeting_id, "title": "Réunion d'équipe", "agenda": "1. Tour de table\n2. Points en cours\n3. Divers",
           "content_markdown": dumps([paragraph(text("Compte-rendu."))]), "status": "redige",
           "meeting_date": "2026-10-11", "author": person(RESP, "responsable"),
           "created_at": "2026-10-11T18:00:00+00:00", "updated_at": "2026-10-11T19:00:00+00:00", "is_locked": False}
    doc.update(overrides)
    return doc


def test_legacy_meeting_is_normalised_without_writing():
    insert("meeting_summaries", legacy_meeting())
    doc = h.run(agenda_meetings.get("legacy-1"))
    detail = agenda_meetings.to_detail(doc, VIEWER_STAFF)

    assert [item["id"] for item in detail["agenda_items"]] == ["legacy-0", "legacy-1", "legacy-2"]
    assert [item["title"] for item in detail["agenda_items"]] == ["Tour de table", "Points en cours", "Divers"]
    assert all(item["done"] is False for item in detail["agenda_items"])
    assert detail["agenda_preview"] == ["Tour de table", "Points en cours", "Divers"] and detail["agenda_count"] == 3
    assert detail["content_format"] == "blocknote" and detail["revision"] == 0
    assert detail["phase"] == "redige" and detail["status"] == "redige"
    assert detail["participants"] == [] and detail["decisions"] == [] and detail["action_items"] == []
    assert detail["reminders"] == {"enabled": False, "offsets": [], "ping_role": False, "schedule": []}
    assert detail["start_time"] is None and detail["location"] == "" and detail["cancelled"] is False
    assert detail["excerpt"] == "" and detail["word_count"] == 0  # dérivés pas encore calculés : rien d'inventé
    assert detail["can_edit"] is True and detail["can_manage"] is False
    assert detail["updated_by"] is None and detail["locked_by"] is None and detail["participants_absent"] == []
    assert detail["viewer"] == VIEWER_STAFF
    # Rien n'a été écrit.
    assert set(stored("meeting_summaries", "legacy-1")) == set(legacy_meeting())


def test_plain_text_and_empty_legacy_content_formats():
    insert("meeting_summaries", legacy_meeting("txt", content_markdown="Ancien texte brut\navec deux lignes"))
    detail = agenda_meetings.to_detail(h.run(agenda_meetings.get("txt")), VIEWER_STAFF)
    assert detail["content_format"] == "text" and detail["content_markdown"] == "Ancien texte brut\navec deux lignes"

    insert("meeting_summaries", legacy_meeting("vide", content_markdown="", status="en_attente_resume"))
    detail = agenda_meetings.to_detail(h.run(agenda_meetings.get("vide")), VIEWER_STAFF)
    assert detail["content_format"] == "empty" and detail["content_markdown"] == "" and detail["phase"] == "a_rediger"

    insert("meeting_summaries", legacy_meeting("deep", content_markdown="[" * 20000 + "]" * 20000))
    detail = agenda_meetings.to_detail(h.run(agenda_meetings.get("deep")), VIEWER_STAFF)
    assert detail["content_format"] == "text"

    # Le contenu stocké avant la refonte est nettoyé aussi à la lecture.
    dirty = dumps([paragraph(link("javascript:alert(1)", text("lien")))])
    insert("meeting_summaries", legacy_meeting("dirty", content_markdown=dirty))
    detail = agenda_meetings.to_detail(h.run(agenda_meetings.get("dirty")), VIEWER_STAFF)
    assert "javascript" not in detail["content_markdown"] and "lien" in detail["content_markdown"]


def test_legacy_agenda_items_strip_bullets_and_blank_lines():
    items = agenda_meetings.legacy_agenda_items("1. Un\n2) Deux\n- Trois\n• Quatre\n* Cinq\n\n   \n  6. Six\nSept")
    assert [item["title"] for item in items] == ["Un", "Deux", "Trois", "Quatre", "Cinq", "Six", "Sept"]
    assert [item["id"] for item in items][:2] == ["legacy-0", "legacy-1"]
    assert agenda_meetings.legacy_agenda_items("") == [] and agenda_meetings.legacy_agenda_items(None) == []
    assert len(agenda_meetings.legacy_agenda_items("\n".join(f"{n}. point" for n in range(80)))) == 50
    assert agenda_meetings.agenda_text([{"title": "Tour"}, {"title": "  "}, {"title": "Divers"}]) == "1. Tour\n2. Divers"
    assert len(agenda_meetings.agenda_text([{"title": "x" * 200}] * 50)) <= 4000


def test_stored_agenda_items_win_over_legacy_text_and_ids_are_deduplicated():
    doc = legacy_meeting(agenda_items=[{"id": "a1", "title": "Un", "done": True}, {"id": "a1", "title": "Deux"},
                                       {"id": "bad id", "title": "Trois"}, {"id": "a4", "title": "  "}, "intrus"])
    items = agenda_meetings.agenda_items_of(doc)
    assert [item["title"] for item in items] == ["Un", "Deux", "Trois"]
    assert len({item["id"] for item in items}) == 3 and items[0] == {"id": "a1", "title": "Un", "done": True}


def test_meeting_phases(monkeypatch):
    def doc(date, start=None, **extra):
        return {"id": "m", "meeting_date": date, "start_time": start, "status": "redige", **extra}

    phase = agenda_meetings.phase
    assert phase(doc("2026-10-26")) == "a_venir"
    assert phase(doc("2026-10-25")) == "a_venir"  # aujourd'hui sans heure
    assert phase(doc("2026-10-25", "13:01")) == "a_venir"
    assert phase(doc("2026-10-25", "13:00")) == "redige"  # 13:00 à Paris : déjà commencée
    assert phase(doc("2026-10-25", "09:00")) == "redige"
    assert phase(doc("2026-10-24")) == "redige"
    assert phase(doc("2026-10-24", status="en_attente_resume")) == "a_rediger"
    assert phase(doc("2026-10-24", cancelled=True)) == "annulee"
    assert phase(doc("2026-12-01", cancelled=True)) == "annulee"
    assert phase(doc("2026-10-25", "09:00", status="en_attente_resume")) == "a_rediger"
    # Heure donnée : l'heure murale de Paris compte, pas l'UTC (22:30Z = 23:30 à Paris).
    assert phase(doc("2026-10-25", "23:00"), datetime(2026, 10, 25, 22, 30, tzinfo=timezone.utc)) == "redige"
    # Instant naïf (BSON) : lu comme de l'UTC.
    assert phase(doc("2026-10-25", "13:01"), datetime(2026, 10, 25, 12, 0)) == "a_venir"
    # Sans champ `status` : déduit du contenu, sinon en attente.
    assert phase({"id": "m", "meeting_date": "2026-10-01", "content_markdown": "[]x"}) == "redige"
    assert phase({"id": "m", "meeting_date": "2026-10-01", "content_markdown": ""}) == "a_rediger"


def test_meeting_summary_fields_for_filters_and_lists():
    doc = legacy_meeting("s1", agenda="", agenda_items=[{"id": f"a{n}", "title": f"Point {n}", "done": n < 3} for n in range(7)],
                         participants=[{**person(STAFF), "attendance": "present"}, {**person(ANIM), "attendance": "bogus"}],
                         decisions=[{"id": "d1", "text": "Oui"}],
                         action_items=[{"id": "x1", "text": "A", "done": False}, {"id": "x2", "text": "B", "done": True}],
                         excerpt="Début…", word_count=12, start_time="21:00", location="Vocal Staff",
                         updated_at="2026-10-23T09:10:00+00:00")
    summary = agenda_meetings.to_summary(doc, VIEWER_STAFF)

    assert summary["agenda_preview"] == [f"Point {n}" for n in range(5)] and summary["agenda_count"] == 7
    assert summary["agenda_done_count"] == 3 and summary["decisions_count"] == 1
    assert summary["actions_count"] == 2 and summary["open_actions_count"] == 1
    assert summary["participants_count"] == 2 and summary["participant_ids"] == [STAFF, ANIM]
    assert summary["is_participant"] is True and agenda_meetings.to_summary(doc, VIEWER_OTHER)["is_participant"] is False
    assert summary["can_manage"] is False and agenda_meetings.to_summary(doc, VIEWER_RESP)["can_manage"] is True
    assert summary["excerpt"] == "Début…" and summary["word_count"] == 12 and summary["phase"] == "redige"
    assert "content_markdown" not in summary and "agenda_items" not in summary
    detail = agenda_meetings.to_detail(doc, VIEWER_STAFF, participants_absent=[STAFF, "intrus", STAFF])
    assert detail["participants_absent"] == [STAFF]
    assert [p["attendance"] for p in detail["participants"]] == ["present", "invite"]


# ---------------------------------------------------------------------------
# Réunions : création et écriture
# ---------------------------------------------------------------------------

def make_meeting(**overrides) -> dict:
    payload = {"title": "Réunion mensuelle de novembre", "meeting_date": "2026-10-30", "start_time": "20:30",
               "end_time": "21:30", "location": "Vocal Staff"}
    payload.update(overrides)
    return h.run(agenda_meetings.create(payload, H_RESP, VIEWER_RESP))


def patch_meeting(meeting_id: str, viewer=VIEWER_STAFF, helper=H_STAFF, **fields):
    return h.run(agenda_meetings.patch(meeting_id, fields, helper, viewer))


def test_create_meeting_defaults_and_validation():
    meeting = make_meeting(agenda_items=[{"title": "Tour de table"}, {"title": "Planning", "id": "mon-id", "done": True}],
                           participant_ids=[STAFF, RESP])
    assert meeting["agenda"] == "1. Tour de table\n2. Planning"
    assert meeting["agenda_items"][1] == {"id": "mon-id", "title": "Planning", "done": True}
    assert len(meeting["agenda_items"][0]["id"]) == 36
    assert meeting["revision"] == 0 and meeting["content_markdown"] == "" and meeting["status"] == "en_attente_resume"
    assert meeting["reminders"] == {"enabled": True, "offsets": ["J-7", "J-2", "J-1", "H-1"], "ping_role": False}
    assert [p["attendance"] for p in meeting["participants"]] == ["invite", "invite"]
    assert meeting["author"]["id"] == RESP and meeting["is_locked"] is False and meeting["cancelled"] is False
    assert "tour de table" in meeting["search_text"] and meeting["word_count"] == 0 and meeting["excerpt"] == ""
    assert stored("meeting_summaries", meeting["id"])["revision"] == 0

    raises_http(agenda_meetings.create({"title": "T", "meeting_date": "2026-10-30", "end_time": "21:00"}, H_RESP, VIEWER_RESP),
                422, "Indiquez une heure de début.")
    raises_http(agenda_meetings.create({"title": "T", "meeting_date": "2026-10-30", "start_time": "21:00",
                                        "end_time": "20:00"}, H_RESP, VIEWER_RESP), 422,
                "L'heure de fin doit suivre l'heure de début.")
    raises_http(agenda_meetings.create({"title": "T", "meeting_date": "2020-01-01"}, H_RESP, VIEWER_RESP), 422,
                "Date hors limites.")
    raises_http(agenda_meetings.create({"title": "T", "meeting_date": "2026-10-30", "participant_ids": [UNKNOWN]},
                                       H_RESP, VIEWER_RESP), 422, f"Participant inconnu : {UNKNOWN}.")
    minimal = h.run(agenda_meetings.create({"title": "Simple", "meeting_date": "2026-10-30"}, H_RESP, VIEWER_RESP))
    assert minimal["start_time"] is None and minimal["agenda"] == "" and minimal["participants"] == []


def test_patch_revision_conflict_shape():
    meeting = make_meeting()
    first = patch_meeting(meeting["id"], expected_revision=0, title="Nouveau titre")
    assert first["revision"] == 1 and first["title"] == "Nouveau titre"

    second = patch_meeting(meeting["id"], viewer=VIEWER_RESP, helper=H_RESP, expected_revision=0, title="Autre")
    assert isinstance(second, JSONResponse) and second.status_code == 409
    body = json.loads(second.body)
    assert body["code"] == "revision_conflict" and body["current_revision"] == 1
    assert body["detail"] == "Ce compte-rendu a été modifié par quelqu'un d'autre. Rechargez avant de continuer."
    assert body["updated_by"]["id"] == STAFF and body["updated_at"] == "2026-10-25T12:00:00+00:00"
    assert stored("meeting_summaries", meeting["id"])["title"] == "Nouveau titre"
    # Révision en avance sur la base : conflit aussi.
    assert patch_meeting(meeting["id"], expected_revision=5, title="x").status_code == 409


def test_patch_requires_a_revision_and_works_on_legacy_documents():
    meeting = make_meeting()
    raises_http(agenda_meetings.patch(meeting["id"], {"expected_revision": None, "title": "x"}, H_STAFF, VIEWER_STAFF), 422,
                "Champ obligatoire : révision.")
    with pytest.raises(Exception):
        h.run(agenda_meetings.patch(meeting["id"], {"title": "x"}, H_STAFF, VIEWER_STAFF))

    # Ancien document : ni `revision` ni `is_locked`.
    legacy = legacy_meeting("old")
    del legacy["is_locked"]
    insert("meeting_summaries", legacy)
    out = patch_meeting("old", expected_revision=0, title="Titre modernisé")
    assert out["revision"] == 1 and stored("meeting_summaries", "old")["revision"] == 1
    assert stored("meeting_summaries", "old")["updated_by"]["id"] == STAFF
    assert patch_meeting("old", expected_revision=0, title="Encore").status_code == 409
    raises_http(agenda_meetings.patch("inconnue", {"expected_revision": 0}, H_STAFF, VIEWER_STAFF), 404,
                "Réunion introuvable.")
    for bad in ("a.b", "$x", "x" * 65):
        raises_http(agenda_meetings.patch(bad, {"expected_revision": 0}, H_STAFF, VIEWER_STAFF), 404, "Réunion introuvable.")


def test_patch_reserved_fields_require_responsable():
    meeting = make_meeting()
    message = "Seul un responsable peut modifier la date, les participants, les rappels ou l'annulation."
    for fields in ({"meeting_date": "2026-11-02"}, {"start_time": "10:00"}, {"end_time": None}, {"location": "Ailleurs"},
                   {"participant_ids": [STAFF]}, {"reminders": {"enabled": False}}, {"cancelled": True},
                   {"cancel_reason": "Raison"}):
        raises_http(agenda_meetings.patch(meeting["id"], {"expected_revision": 0, **fields}, H_STAFF, VIEWER_STAFF), 403,
                    message)
    assert stored("meeting_summaries", meeting["id"])["revision"] == 0

    blocks = dumps([paragraph(text("Compte-rendu écrit"))])
    out = patch_meeting(meeting["id"], expected_revision=0, content_markdown=blocks, title="Écrit")
    assert out["status"] == "redige" and out["revision"] == 1
    out = patch_meeting(meeting["id"], viewer=VIEWER_RESP, helper=H_RESP, expected_revision=1, meeting_date="2026-11-02",
                        location="Ailleurs", cancelled=True, cancel_reason="Malade")
    assert out["meeting_date"] == "2026-11-02" and out["location"] == "Ailleurs"
    assert out["cancelled"] is True and out["cancel_reason"] == "Malade"
    out = patch_meeting(meeting["id"], viewer=VIEWER_RESP, helper=H_RESP, expected_revision=2, cancelled=False)
    assert out["cancelled"] is False and out["cancel_reason"] == ""
    raises_http(agenda_meetings.patch(meeting["id"], {"expected_revision": 3, "meeting_date": "2020-01-01"}, H_RESP,
                                      VIEWER_RESP), 422, "Date hors limites.")
    raises_http(agenda_meetings.patch(meeting["id"], {"expected_revision": 3, "meeting_date": None}, H_RESP, VIEWER_RESP),
                422, "Champ obligatoire : date.")
    raises_http(agenda_meetings.patch(meeting["id"], {"expected_revision": 3, "cancelled": None}, H_RESP, VIEWER_RESP),
                422, "Champ obligatoire : annulation.")


def test_patch_content_is_sanitised_derived_and_status_follows_content():
    meeting = make_meeting()
    dirty = dumps([paragraph(link("javascript:alert(1)", text("lien piégé")), text(" et du texte"))])
    out = patch_meeting(meeting["id"], expected_revision=0, content_markdown=dirty)
    row = stored("meeting_summaries", meeting["id"])

    assert "javascript" not in row["content_markdown"] and "lien piégé" in row["content_markdown"]
    assert row["content_text"] == "lien piégé et du texte" and row["word_count"] == 5
    assert row["excerpt"] == "lien piégé et du texte" and "lien piege" in row["search_text"]
    assert row["status"] == "redige" and out["status"] == "redige"

    raises_http(agenda_meetings.patch(meeting["id"], {"expected_revision": 1, "content_markdown": "bonjour"}, H_STAFF,
                                      VIEWER_STAFF), 422, "Contenu illisible.")
    assert stored("meeting_summaries", meeting["id"])["revision"] == 1

    emptied = patch_meeting(meeting["id"], expected_revision=1, content_markdown=dumps([1, "a"]))
    row = stored("meeting_summaries", meeting["id"])
    assert row["content_markdown"] == "" and row["status"] == "en_attente_resume" and row["content_text"] == ""
    assert row["word_count"] == 0 and emptied["revision"] == 2
    # Une réécriture du titre seul garde le texte déjà extrait.
    patch_meeting(meeting["id"], expected_revision=2, content_markdown=dirty)
    patch_meeting(meeting["id"], expected_revision=3, title="Seulement le titre")
    row = stored("meeting_summaries", meeting["id"])
    assert row["content_text"] == "lien piégé et du texte" and "seulement le titre" in row["search_text"]
    assert patch_meeting(meeting["id"], expected_revision=4, content_markdown=None)["status"] == "en_attente_resume"


def test_patch_agenda_decisions_and_list_ids():
    meeting = make_meeting(agenda_items=[{"title": "Un"}])
    out = patch_meeting(meeting["id"], expected_revision=0,
                        agenda_items=[{"id": "p1", "title": " Point 1 ", "done": True}, {"title": "Point 2"},
                                      {"id": "p1", "title": "Doublon"}],
                        decisions=[{"id": "d1", "text": "On fait ça"}, {"text": "Et ça"}])
    row = stored("meeting_summaries", meeting["id"])
    assert row["agenda"] == "1. Point 1\n2. Point 2\n3. Doublon"
    assert row["agenda_items"][0] == {"id": "p1", "title": "Point 1", "done": True}
    assert len({item["id"] for item in row["agenda_items"]}) == 3
    assert [d["text"] for d in row["decisions"]] == ["On fait ça", "Et ça"] and len(row["decisions"][1]["id"]) == 36
    assert "on fait ca" in row["search_text"] and "point 2" in row["search_text"]
    assert out["revision"] == 1

    out = patch_meeting(meeting["id"], expected_revision=1, agenda_items=None, decisions=None)
    assert stored("meeting_summaries", meeting["id"])["agenda_items"] == [] and out["decisions"] == []
    assert stored("meeting_summaries", meeting["id"])["agenda"] == ""


def test_patch_time_semantics():
    meeting = make_meeting()
    out = patch_meeting(meeting["id"], viewer=VIEWER_RESP, helper=H_RESP, expected_revision=0, start_time=None)
    assert out["start_time"] is None and out["end_time"] is None
    assert stored("meeting_summaries", meeting["id"])["end_time"] is None

    raises_http(agenda_meetings.patch(meeting["id"], {"expected_revision": 1, "start_time": None, "end_time": "22:00"},
                                      H_RESP, VIEWER_RESP), 422, "Indiquez une heure de début.")
    raises_http(agenda_meetings.patch(meeting["id"], {"expected_revision": 1, "end_time": "22:00"}, H_RESP, VIEWER_RESP),
                422, "Indiquez une heure de début.")
    out = patch_meeting(meeting["id"], viewer=VIEWER_RESP, helper=H_RESP, expected_revision=1, start_time="20:00",
                        end_time="21:00")
    assert out["end_time"] == "21:00"
    raises_http(agenda_meetings.patch(meeting["id"], {"expected_revision": 2, "end_time": "19:00"}, H_RESP, VIEWER_RESP),
                422, "L'heure de fin doit suivre l'heure de début.")
    out = patch_meeting(meeting["id"], viewer=VIEWER_RESP, helper=H_RESP, expected_revision=2, end_time=None, location=None)
    assert out["end_time"] is None and out["location"] == ""


def test_patch_reminders_merge_for_legacy_and_new_meetings():
    insert("meeting_summaries", legacy_meeting("old", meeting_date="2026-11-10"))
    out = patch_meeting("old", viewer=VIEWER_RESP, helper=H_RESP, expected_revision=0, reminders={"enabled": True})
    assert out["reminders"] == {"enabled": True, "offsets": ["J-7", "J-2", "J-1", "H-1"], "ping_role": False}
    out = patch_meeting("old", viewer=VIEWER_RESP, helper=H_RESP, expected_revision=1, reminders={"offsets": ["J-1", "H-1"]})
    assert out["reminders"]["offsets"] == ["J-1", "H-1"] and out["reminders"]["enabled"] is True
    out = patch_meeting("old", viewer=VIEWER_RESP, helper=H_RESP, expected_revision=2, reminders={"ping_role": True})
    assert out["reminders"] == {"enabled": True, "offsets": ["J-1", "H-1"], "ping_role": True}
    out = patch_meeting("old", viewer=VIEWER_RESP, helper=H_RESP, expected_revision=3, reminders={"enabled": False})
    assert out["reminders"]["enabled"] is False and out["reminders"]["ping_role"] is True


def test_locked_meeting_refuses_patch_but_not_action_toggle():
    meeting = make_meeting()
    patch_meeting(meeting["id"], expected_revision=0, action_items=[{"id": "x1", "text": "Planning"}])
    before = stored("meeting_summaries", meeting["id"])["revision"]

    locked = h.run(agenda_meetings.set_lock(meeting["id"], True, H_RESP))
    assert locked["is_locked"] is True and locked["locked_by"]["id"] == RESP and locked["locked_at"]
    raises_http(agenda_meetings.patch(meeting["id"], {"expected_revision": before, "title": "x"}, H_STAFF, VIEWER_STAFF),
                403, "Ce résumé est verrouillé.")
    toggled = h.run(agenda_meetings.toggle_action(meeting["id"], "x1", True, H_STAFF))
    assert toggled["item"]["done"] is True and toggled["revision"] == before
    unlocked = h.run(agenda_meetings.set_lock(meeting["id"], False, H_RESP))
    assert unlocked["is_locked"] is False and unlocked["locked_by"] is None and unlocked["locked_at"] is None
    assert stored("meeting_summaries", meeting["id"])["revision"] == before
    # Idempotent.
    assert h.run(agenda_meetings.set_lock(meeting["id"], False, H_RESP))["is_locked"] is False
    raises_http(agenda_meetings.set_lock("inconnue", True, H_RESP), 404, "Réunion introuvable.")
    raises_http(agenda_meetings.set_lock("a.b", True, H_RESP), 404, "Réunion introuvable.")


def test_patch_after_concurrent_lock_is_403_not_409(monkeypatch):
    meeting = make_meeting()
    original_get = agenda_meetings.get

    async def lock_after_read(meeting_id):
        doc = await original_get(meeting_id)
        await db.meeting_summaries.update_one({"id": meeting_id}, {"$set": {"is_locked": True}})
        return doc

    monkeypatch.setattr(agenda_meetings, "get", lock_after_read)
    raises_http(agenda_meetings.patch(meeting["id"], {"expected_revision": 0, "title": "Perdu"}, H_STAFF, VIEWER_STAFF),
                403, "Ce résumé est verrouillé.")
    row = stored("meeting_summaries", meeting["id"])
    assert row["title"] == "Réunion mensuelle de novembre" and row["revision"] == 0


def test_patch_after_concurrent_write_is_409_and_after_delete_is_404(monkeypatch):
    meeting = make_meeting()
    original_get = agenda_meetings.get

    async def write_after_read(meeting_id):
        doc = await original_get(meeting_id)
        await db.meeting_summaries.update_one({"id": meeting_id}, {"$set": {"revision": 4}})
        return doc

    monkeypatch.setattr(agenda_meetings, "get", write_after_read)
    response = patch_meeting(meeting["id"], expected_revision=0, title="Perdu")
    assert response.status_code == 409 and json.loads(response.body)["current_revision"] == 4

    async def delete_after_read(meeting_id):
        doc = await original_get(meeting_id)
        await db.meeting_summaries.delete_one({"id": meeting_id})
        return doc

    monkeypatch.setattr(agenda_meetings, "get", delete_after_read)
    raises_http(agenda_meetings.patch(meeting["id"], {"expected_revision": 4, "title": "x"}, H_STAFF, VIEWER_STAFF), 404,
                "Réunion introuvable.")


def test_action_toggle_sets_and_clears_done_fields_without_revision():
    meeting = make_meeting()
    patch_meeting(meeting["id"], expected_revision=0, action_items=[{"id": "x1", "text": "Planning"}])
    patch_meeting(meeting["id"], expected_revision=1, content_markdown=dumps([paragraph(text("Texte"))]))
    revision = stored("meeting_summaries", meeting["id"])["revision"]
    assert revision == 2

    result = h.run(agenda_meetings.toggle_action(meeting["id"], "x1", True, H_OTHER))
    assert result["meeting_id"] == meeting["id"] and result["revision"] == revision
    assert result["item"]["done"] is True and result["item"]["done_at"] == "2026-10-25T12:00:00Z"
    assert result["item"]["done_by"]["id"] == OTHER
    row = stored("meeting_summaries", meeting["id"])
    assert row["revision"] == revision and row["updated_by"]["id"] == OTHER
    assert row["action_items"][0]["done"] is True
    assert row["content_markdown"] and row["status"] == "redige"

    again = h.run(agenda_meetings.toggle_action(meeting["id"], "x1", True, H_STAFF))
    assert again["item"]["done_by"]["id"] == OTHER  # déjà fait : rien ne change

    cleared = h.run(agenda_meetings.toggle_action(meeting["id"], "x1", False, H_STAFF))
    assert cleared["item"]["done"] is False and cleared["item"]["done_at"] is None and cleared["item"]["done_by"] is None

    for bad_action in ("legacy-0", "inconnue", "a.b"):
        raises_http(agenda_meetings.toggle_action(meeting["id"], bad_action, True, H_STAFF), 404, "Action introuvable.")
    raises_http(agenda_meetings.toggle_action("inconnue", "x1", True, H_STAFF), 404, "Réunion introuvable.")
    raises_http(agenda_meetings.toggle_action("a.b", "x1", True, H_STAFF), 404, "Réunion introuvable.")


def test_toggle_and_lock_do_not_cause_conflicts():
    meeting = make_meeting()
    patch_meeting(meeting["id"], expected_revision=0, action_items=[
        {"id": "x1", "text": "Planning"}, {"id": "x2", "text": "Autre"}])
    revision = stored("meeting_summaries", meeting["id"])["revision"]

    h.run(agenda_meetings.toggle_action(meeting["id"], "x1", True, H_OTHER))
    h.run(agenda_meetings.set_lock(meeting["id"], True, H_RESP))
    h.run(agenda_meetings.set_lock(meeting["id"], False, H_RESP))
    assert stored("meeting_summaries", meeting["id"])["revision"] == revision

    # Le rédacteur envoie ses actions sans `done` : l'action cochée par un autre reste cochée.
    out = patch_meeting(meeting["id"], expected_revision=revision, content_markdown=dumps([paragraph(text("Mon texte"))]),
                        action_items=[{"id": "x1", "text": "Planning"}, {"id": "x2", "text": "Autre modifié"}])
    assert not isinstance(out, JSONResponse) and out["revision"] == revision + 1
    first = out["action_items"][0]
    assert first["done"] is True and first["done_by"]["id"] == OTHER and first["done_at"] == "2026-10-25T12:00:00Z"
    assert out["action_items"][1]["text"] == "Autre modifié" and out["action_items"][1]["done"] is False


def test_done_semantics_per_action_item():
    meeting = make_meeting()
    patch_meeting(meeting["id"], expected_revision=0, action_items=[{"id": "x1", "text": "A"}])
    out = patch_meeting(meeting["id"], expected_revision=1, action_items=[{"id": "x1", "text": "A", "done": True}])
    done_at, done_by = out["action_items"][0]["done_at"], out["action_items"][0]["done_by"]
    assert out["action_items"][0]["done"] is True and done_by["id"] == STAFF and done_at == "2026-10-25T12:00:00Z"

    # `done` absent : les trois champs sont gardés (même avec un autre texte).
    out = patch_meeting(meeting["id"], expected_revision=2, action_items=[{"id": "x1", "text": "A bis"}])
    assert out["action_items"][0]["done"] is True and out["action_items"][0]["done_by"] == done_by
    assert out["action_items"][0]["done_at"] == done_at

    # `done: true` sur une action déjà faite : `done_at` ne bouge pas, même plus tard.
    row_before = stored("meeting_summaries", meeting["id"])["action_items"][0]
    out = patch_meeting(meeting["id"], helper=H_OTHER, viewer=VIEWER_OTHER, expected_revision=3,
                        action_items=[{"id": "x1", "text": "A bis", "done": True}])
    assert out["action_items"][0]["done_by"] == done_by
    assert stored("meeting_summaries", meeting["id"])["action_items"][0]["done_at"] == row_before["done_at"]

    # `done: false` vide les champs.
    out = patch_meeting(meeting["id"], expected_revision=4, action_items=[{"id": "x1", "text": "A bis", "done": False}])
    assert out["action_items"][0]["done"] is False and out["action_items"][0]["done_at"] is None
    assert out["action_items"][0]["done_by"] is None

    # Nouvelle action : `done` vaut faux par défaut, vrai si demandé (avec `done_at`).
    out = patch_meeting(meeting["id"], expected_revision=5, action_items=[
        {"id": "x1", "text": "A bis"}, {"text": "Nouvelle"}, {"text": "Déjà faite", "done": True}, {"id": "inconnue", "text": "Id libre"}])
    assert [item["done"] for item in out["action_items"]] == [False, False, True, False]
    assert out["action_items"][2]["done_at"] == "2026-10-25T12:00:00Z"
    assert out["action_items"][3]["id"] == "inconnue" and len(out["action_items"][1]["id"]) == 36


def test_action_assignee_and_due_date_null_semantics():
    meeting = make_meeting()
    patch_meeting(meeting["id"], expected_revision=0, action_items=[
        {"id": "x1", "text": "A", "assignee_id": STAFF, "due_date": "2026-10-30"}])

    out = patch_meeting(meeting["id"], expected_revision=1, action_items=[{"id": "x1", "text": "A modifié"}])
    assert out["action_items"][0]["assignee"]["id"] == STAFF and out["action_items"][0]["due_date"] == "2026-10-30"

    out = patch_meeting(meeting["id"], expected_revision=2, action_items=[{"id": "x1", "text": "A", "assignee_id": None}])
    assert out["action_items"][0]["assignee"] is None and out["action_items"][0]["due_date"] == "2026-10-30"

    out = patch_meeting(meeting["id"], expected_revision=3, action_items=[
        {"id": "x1", "text": "A", "assignee_id": ANIM, "due_date": None}])
    assert out["action_items"][0]["assignee"]["id"] == ANIM and out["action_items"][0]["due_date"] is None
    assert stored("meeting_summaries", meeting["id"])["action_items"][0]["assignee"]["id"] == ANIM

    raises_http(agenda_meetings.patch(meeting["id"], {"expected_revision": 4, "action_items": [
        {"text": "B", "assignee_id": UNKNOWN}]}, H_STAFF, VIEWER_STAFF), 422, f"Participant inconnu : {UNKNOWN}.")


def test_departed_people_keep_their_stored_identity():
    meeting = make_meeting(participant_ids=[STAFF])
    patch_meeting(meeting["id"], expected_revision=0, action_items=[
        {"id": "x1", "text": "Planning", "assignee_id": STAFF}, {"id": "x2", "text": "Compte-rendu"}])
    stored_identity = stored("meeting_summaries", meeting["id"])["action_items"][0]["assignee"]

    # Le membre quitte le staff : son identité reste, sans interroger l'annuaire.
    h.fake_discord.member_roles[STAFF] = []
    agenda_people.reset_state()
    h.fake_discord.calls.clear()
    out = patch_meeting(meeting["id"], expected_revision=1, action_items=[
        {"id": "x1", "text": "Planning", "assignee_id": STAFF}, {"id": "x2", "text": "Compte-rendu", "done": True},
        {"text": "Nouvelle sans assigné"}])
    assert out["action_items"][0]["assignee"] == stored_identity and out["action_items"][1]["done"] is True
    assert not [call for call in h.fake_discord.calls if call.endswith("/members")]

    h.fake_discord.member_roles[STAFF] = []
    out = h.run(agenda_meetings.patch(meeting["id"], {"expected_revision": 2, "participant_ids": [STAFF, ANIM]}, H_RESP,
                                      VIEWER_RESP))
    assert [p["id"] for p in out["participants"]] == [STAFF, ANIM]


def test_participants_directory_down_only_matters_for_new_ids(monkeypatch):
    meeting = make_meeting(participant_ids=[STAFF])
    agenda_people.reset_state()

    async def broken(self, role_id):
        raise OSError("réseau")

    monkeypatch.setattr(DiscordService, "fetch_helpers", broken)
    # Aucun id nouveau : l'annuaire n'est pas appelé.
    out = patch_meeting(meeting["id"], viewer=VIEWER_RESP, helper=H_RESP, expected_revision=0, participant_ids=[STAFF],
                        title="Sans annuaire")
    assert out["title"] == "Sans annuaire"
    patch_meeting(meeting["id"], expected_revision=1, action_items=[{"text": "Sans assigné"}])
    raises_http(agenda_meetings.patch(meeting["id"], {"expected_revision": 2, "participant_ids": [STAFF, ANIM]}, H_RESP,
                                      VIEWER_RESP), 503, "Liste du staff indisponible, réessayez.")
    raises_http(agenda_meetings.patch(meeting["id"], {"expected_revision": 2, "action_items": [
        {"text": "x", "assignee_id": ANIM}]}, H_STAFF, VIEWER_STAFF), 503, "Liste du staff indisponible, réessayez.")
    assert stored("meeting_summaries", meeting["id"])["revision"] == 2


def test_attendance_kept_when_participants_are_replaced():
    meeting = make_meeting(participant_ids=[STAFF, RESP])
    out = patch_meeting(meeting["id"], expected_revision=0, attendance={STAFF: "present", RESP: "absent"})
    assert {p["id"]: p["attendance"] for p in out["participants"]} == {STAFF: "present", RESP: "absent"}

    out = patch_meeting(meeting["id"], viewer=VIEWER_RESP, helper=H_RESP, expected_revision=1,
                        participant_ids=[STAFF, ANIM], attendance={ANIM: "excuse"})
    assert {p["id"]: p["attendance"] for p in out["participants"]} == {STAFF: "present", ANIM: "excuse"}
    assert [p["id"] for p in stored("meeting_summaries", meeting["id"])["participants"]] == [STAFF, ANIM]

    raises_http(agenda_meetings.patch(meeting["id"], {"expected_revision": 2, "attendance": {RESP: "present"}}, H_STAFF,
                                      VIEWER_STAFF), 422, f"Participant inconnu : {RESP}.")
    assert stored("meeting_summaries", meeting["id"])["revision"] == 2
    with pytest.raises(Exception):
        h.run(agenda_meetings.patch(meeting["id"], {"expected_revision": 2, "attendance": {STAFF: "bof"}}, H_STAFF,
                                    VIEWER_STAFF))
    # Présence d'un document ancien : valeur inconnue lue comme « invite ».
    insert("meeting_summaries", legacy_meeting("old", participants=[{**person(STAFF), "attendance": "n'importe"}]))
    out = patch_meeting("old", expected_revision=0, attendance={STAFF: "present"})
    assert out["participants"][0]["attendance"] == "present"


def test_delete_meeting_refuses_locked_and_unknown():
    meeting = make_meeting()
    h.run(agenda_meetings.set_lock(meeting["id"], True, H_RESP))
    raises_http(agenda_meetings.delete(meeting["id"]), 403, "Ce résumé est verrouillé.")
    assert stored("meeting_summaries", meeting["id"]) is not None
    h.run(agenda_meetings.set_lock(meeting["id"], False, H_RESP))
    h.run(agenda_meetings.delete(meeting["id"]))
    assert stored("meeting_summaries", meeting["id"]) is None
    raises_http(agenda_meetings.delete(meeting["id"]), 404, "Réunion introuvable.")
    raises_http(agenda_meetings.delete("a.b"), 404, "Réunion introuvable.")


# ---------------------------------------------------------------------------
# Réunions : liste et vue d'ensemble
# ---------------------------------------------------------------------------

def seed_listing() -> None:
    """Quatre réunions (à venir, à rédiger, rédigée, annulée), insérées au format stocké."""
    base = {"author": person(RESP), "created_at": "2026-10-01T10:00:00+00:00", "updated_at": "2026-10-01T10:00:00+00:00"}
    docs = [
        {**base, "id": "futur", "title": "Préparation de l'événement d'hiver", "meeting_date": "2026-10-30", "start_time": "20:30",
         "status": "en_attente_resume", "content_markdown": "", "content_text": "", "excerpt": "",
         "search_text": agenda_meetings.normalize_search("Préparation de l'événement d'hiver")},
        {**base, "id": "futur2", "title": "Plus tard", "meeting_date": "2026-11-20", "status": "en_attente_resume",
         "search_text": "plus tard", "content_markdown": ""},
        {**base, "id": "a-ecrire", "title": "Point modération", "meeting_date": "2026-10-20", "status": "en_attente_resume",
         "search_text": "point moderation", "content_markdown": "",
         "action_items": [{"id": "x1", "text": "Planning", "assignee": person(STAFF), "due_date": "2026-10-28", "done": False},
                          {"id": "x2", "text": "Autre", "assignee": person(ANIM), "due_date": "2026-10-27", "done": False},
                          {"id": "x3", "text": "Faite", "assignee": person(STAFF), "due_date": None, "done": True}]},
        {**base, "id": "redigee", "title": "Bilan", "meeting_date": "2026-10-10", "status": "redige",
         "search_text": "bilan planning des permanences", "content_markdown": "[]x", "excerpt": "Bilan…",
         "action_items": [{"id": "y1", "text": "Sans échéance", "assignee": person(STAFF), "due_date": None, "done": False},
                          {"id": "y2", "text": "Sans assigné", "assignee": None, "due_date": "2026-10-26", "done": False}]},
        {**base, "id": "annulee", "title": "Annulée", "meeting_date": "2026-10-22", "status": "redige", "cancelled": True,
         "search_text": "annulee", "content_markdown": "[]x",
         "action_items": [{"id": "z1", "text": "Ignorée", "assignee": person(STAFF), "done": False}]},
    ]
    for doc in docs:
        insert("meeting_summaries", doc)


def test_list_meetings_phases_counts_and_order():
    seed_listing()

    everything = h.run(agenda_meetings.list_meetings())
    assert everything["counts"] == {"all": 5, "a_venir": 2, "a_rediger": 1, "redige": 1, "annulee": 1}
    assert [doc["id"] for doc in everything["items"]] == ["futur2", "futur", "annulee", "a-ecrire", "redigee"]
    assert everything["total"] == 5

    upcoming = h.run(agenda_meetings.list_meetings(phase="a_venir"))
    assert [doc["id"] for doc in upcoming["items"]] == ["futur", "futur2"]  # croissant
    assert upcoming["counts"] == everything["counts"] and upcoming["total"] == 2
    assert [doc["id"] for doc in h.run(agenda_meetings.list_meetings(phase="a_rediger"))["items"]] == ["a-ecrire"]
    assert [doc["id"] for doc in h.run(agenda_meetings.list_meetings(phase="annulee"))["items"]] == ["annulee"]

    page = h.run(agenda_meetings.list_meetings(limit=2, offset=1))
    assert [doc["id"] for doc in page["items"]] == ["futur", "annulee"] and page["total"] == 5
    assert h.run(agenda_meetings.list_meetings(limit=1000, offset=-4))["total"] == 5
    raises_http(agenda_meetings.list_meetings(phase="n'importe quoi"), 422)


def test_list_meetings_search_is_accent_insensitive_and_escaped():
    seed_listing()

    found = h.run(agenda_meetings.list_meetings(q="evenement"))
    assert [doc["id"] for doc in found["items"]] == ["futur"]
    assert [doc["id"] for doc in h.run(agenda_meetings.list_meetings(q="ÉVÉNEMENT"))["items"]] == ["futur"]
    assert [doc["id"] for doc in h.run(agenda_meetings.list_meetings(q="planning"))["items"]] == ["redigee"]
    assert h.run(agenda_meetings.list_meetings(q="hiver.*"))["total"] == 0
    assert h.run(agenda_meetings.list_meetings(q="(["))["total"] == 0
    # `counts` ne dépend que de la recherche, pas de la phase demandée.
    filtered = h.run(agenda_meetings.list_meetings(q="evenement", phase="redige"))
    assert filtered["items"] == [] and filtered["counts"] == {"all": 1, "a_venir": 1, "a_rediger": 0, "redige": 0, "annulee": 0}


def test_list_meetings_and_overview_never_read_the_content(monkeypatch):
    seed_listing()
    h.run(db.meeting_summaries.update_one({"id": "redigee"}, {"$set": {"content_markdown": "x" * 300000,
                                                                       "content_text": "x" * 1000}}))
    seen = []
    collection_class = type(db.meeting_summaries)
    original_find = collection_class.find

    def spy(self, *args, **kwargs):
        if self.name == "meeting_summaries":
            seen.append(kwargs.get("projection", args[1] if len(args) > 1 else None))
        return original_find(self, *args, **kwargs)

    monkeypatch.setattr(collection_class, "find", spy)
    listing = h.run(agenda_meetings.list_meetings())
    h.run(agenda_meetings.overview(VIEWER_STAFF))

    assert seen and all(projection == agenda_meetings.MEETING_SUMMARY_PROJECTION for projection in seen)
    for doc in listing["items"]:
        assert not {"content_markdown", "content_text", "search_text", "_id"} & doc.keys()
    summary = agenda_meetings.to_summary(next(doc for doc in listing["items"] if doc["id"] == "redigee"), VIEWER_STAFF)
    assert summary["excerpt"] == "Bilan…"
    assert agenda_meetings.MEETING_SUMMARY_PROJECTION == {"_id": 0, "content_markdown": 0, "content_text": 0, "search_text": 0}


def test_overview_next_meeting_to_write_and_open_actions():
    seed_listing()

    overview = h.run(agenda_meetings.overview(VIEWER_STAFF))

    assert overview["today"] == "2026-10-25" and overview["viewer"] == VIEWER_STAFF
    assert overview["next_meeting"]["id"] == "futur" and overview["next_meeting"]["phase"] == "a_venir"
    assert [summary["id"] for summary in overview["to_write"]] == ["a-ecrire"]
    refs = overview["open_actions"]
    # Les miennes d'abord, puis les autres ; échéance croissante, sans échéance en dernier.
    assert [ref["item"]["id"] for ref in refs] == ["x1", "y1", "y2", "x2"]
    assert [ref["is_mine"] for ref in refs] == [True, True, False, False]
    assert refs[0]["meeting_id"] == "a-ecrire" and refs[0]["meeting_title"] == "Point modération"
    assert refs[0]["meeting_date"] == "2026-10-20" and refs[0]["item"]["assignee"]["id"] == STAFF
    assert overview["counts"] == {"a_venir": 2, "a_rediger": 1, "open_actions": 4, "my_open_actions": 2}
    assert "z1" not in [ref["item"]["id"] for ref in refs]  # réunion annulée ignorée

    nobody = h.run(agenda_meetings.overview(VIEWER_OTHER))
    assert nobody["counts"]["my_open_actions"] == 0 and [ref["item"]["id"] for ref in nobody["open_actions"]] == [
        "y2", "x2", "x1", "y1"]


def test_overview_without_meetings_and_with_time_of_day():
    empty = h.run(agenda_meetings.overview(VIEWER_STAFF))
    assert empty["next_meeting"] is None and empty["to_write"] == [] and empty["open_actions"] == []
    assert empty["counts"] == {"a_venir": 0, "a_rediger": 0, "open_actions": 0, "my_open_actions": 0}

    # Réunion du jour déjà commencée : à rédiger ; réunion du jour plus tard : prochaine.
    base = {"author": person(RESP), "search_text": "x", "content_markdown": "", "status": "en_attente_resume"}
    insert("meeting_summaries", {**base, "id": "tot", "title": "Tôt", "meeting_date": "2026-10-25", "start_time": "09:00"})
    insert("meeting_summaries", {**base, "id": "tard", "title": "Tard", "meeting_date": "2026-10-25", "start_time": "18:00"})
    insert("meeting_summaries", {**base, "id": "tard2", "title": "Tard 2", "meeting_date": "2026-10-25", "start_time": "17:00"})
    overview = h.run(agenda_meetings.overview(VIEWER_STAFF))
    assert overview["next_meeting"]["id"] == "tard2"
    assert [summary["id"] for summary in overview["to_write"]] == ["tot"]


def test_overview_survives_damaged_documents():
    insert("meeting_summaries", {"id": "casse", "title": None, "meeting_date": None, "action_items": "n'importe quoi",
                                 "participants": [None, 3, {"id": None}], "agenda_items": [None, {"title": 5}]})
    insert("meeting_summaries", {"id": "casse2", "title": "Ok", "meeting_date": "2026-10-01", "status": "bizarre",
                                 "action_items": [None, {"text": "", "done": False}, {"text": "Bonne", "done": False, "assignee": 5}]})

    overview = h.run(agenda_meetings.overview(VIEWER_STAFF))
    listing = h.run(agenda_meetings.list_meetings())

    assert [ref["item"]["text"] for ref in overview["open_actions"]] == ["Bonne"]
    assert listing["total"] == 2
    for doc in listing["items"]:
        agenda_meetings.to_summary(doc, VIEWER_STAFF)
        agenda_meetings.to_detail(doc, VIEWER_STAFF)
