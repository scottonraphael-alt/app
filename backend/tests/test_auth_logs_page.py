"""Tests hors-ligne du Journal d'activité Responsable : recherche, catégories, période, résumé du jour.

Aucun appel réseau : Discord, MongoDB et httpx sont simulés.
Lancer depuis backend/ : python -m pytest -q -p no:cacheprovider -n 0 tests/test_auth_logs_page.py
"""
import security_harness as h  # noqa: I001  (doit être importé en premier)

from datetime import datetime, timedelta, timezone
from itertools import count
from zoneinfo import ZoneInfo

import pytest

from routers import responsable

PARIS = ZoneInfo("Europe/Paris")
UTC = timezone.utc
BASE = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
_SEQUENCE = count(1)


@pytest.fixture(autouse=True)
def _clean_state():
    h.reset_db()
    h.reset_discord()
    # Le responsable cumule aussi le rôle helper (cas réel : plusieurs rôles Discord).
    h.fake_discord.member_roles[h.USER_IDS["responsable"]].append(h.ROLE_IDS["helper"])
    yield


def _client(role: str = "responsable"):
    client = h.make_client(responsable.router)
    client.cookies.update(h.session_cookies(role))
    return client


def _seed(*logs: dict) -> None:
    documents = []
    for log in logs:
        number = next(_SEQUENCE)
        documents.append(
            {
                "id": log.get("id", f"log-{number:04d}"),
                "created_at": log.get("created_at", BASE + timedelta(minutes=number)),
                "event_type": log["event_type"],
                "helper_id": log.get("helper_id"),
                "username": log.get("username"),
                "ip": "203.0.113.7",
                "user_agent": "pytest",
                "path": "/api/test",
                "method": "POST",
                "status_code": log.get("status_code", 200),
                "details": log.get("details", {}),
            }
        )
    h.run(h.db.auth_logs.insert_many(documents))


def _get(path: str = "/api/responsable/auth-logs", **params):
    return _client().get(path, params=params)


def _ids(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


# --- Accès -----------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/responsable/auth-logs", "/api/responsable/auth-logs/summary"])
def test_staff_only_user_gets_403(path):
    assert _client("staff").get(path).status_code == 403


@pytest.mark.parametrize("path", ["/api/responsable/auth-logs", "/api/responsable/auth-logs/summary"])
def test_anonymous_gets_401(path):
    assert h.make_client(responsable.router).get(path).status_code == 401


# --- Compatibilité des anciens paramètres --------------------------------------------------------


def test_default_response_shape_and_order_unchanged():
    _seed(
        {"id": "a", "event_type": "auth.login.success", "created_at": BASE},
        {"id": "b", "event_type": "authz.forbidden", "created_at": BASE + timedelta(hours=1)},
        {"id": "c", "event_type": "project.created", "created_at": BASE + timedelta(hours=2)},
    )
    response = _get()
    body = response.json()
    assert response.status_code == 200
    assert set(body) == {"total", "items"}
    assert body["total"] == 3
    assert [item["id"] for item in body["items"]] == ["c", "b", "a"]
    assert {"id", "created_at", "event_type", "helper_id", "username", "ip", "path", "method",
            "status_code", "details"} <= set(body["items"][0])


def test_created_at_is_serialized_as_utc():
    _seed({"id": "a", "event_type": "auth.logout", "created_at": BASE})
    created_at = _get().json()["items"][0]["created_at"]
    assert created_at.endswith("Z") or created_at.endswith("+00:00")


def test_old_params_event_type_helper_id_skip_limit():
    _seed(
        {"id": "a", "event_type": "auth.login.success", "helper_id": "111", "username": "Ines"},
        {"id": "b", "event_type": "authz.forbidden", "helper_id": "111", "username": "Ines"},
        {"id": "c", "event_type": "authz.forbidden", "helper_id": "222", "username": "Leo"},
        {"id": "d", "event_type": "authz.forbidden", "helper_id": "222", "username": "Leo"},
    )
    assert _ids(_get(event_type="authz.forbidden")) == ["d", "c", "b"]
    assert _ids(_get(helper_id="111")) == ["b", "a"]
    assert _ids(_get(event_type="authz.forbidden", helper_id="222")) == ["d", "c"]

    page = _get(limit=2, skip=1).json()
    assert page["total"] == 4
    assert [item["id"] for item in page["items"]] == ["c", "b"]


def test_limit_and_text_lengths_are_validated():
    assert _get(limit=0).status_code == 422
    assert _get(limit=201).status_code == 422
    assert _get(skip=-1).status_code == 422
    assert _get(q="x" * 101).status_code == 422
    assert _get(event_type="x" * 101).status_code == 422
    assert _get(helper_id="1" * 65).status_code == 422
    assert _get(categories="x" * 201).status_code == 422


# --- Recherche q -----------------------------------------------------------------------------------


def test_q_matches_acting_username_case_insensitive():
    _seed(
        {"id": "a", "event_type": "auth.login.success", "username": "Ines_Mod", "helper_id": "111"},
        {"id": "b", "event_type": "auth.login.success", "username": "leo", "helper_id": "222"},
    )
    assert _ids(_get(q="ines")) == ["a"]
    assert _ids(_get(q="INES_MOD")) == ["a"]
    assert _ids(_get(q="  leo  ")) == ["b"]
    assert _ids(_get(q="personne")) == []
    assert _get(q="personne").json()["total"] == 0


def test_q_matches_helper_id():
    _seed(
        {"id": "a", "event_type": "auth.login.success", "username": "Ines", "helper_id": "111222333"},
        {"id": "b", "event_type": "auth.login.success", "username": "Leo", "helper_id": "999"},
    )
    assert _ids(_get(q="222333")) == ["a"]


def test_q_matches_member_and_project_details():
    _seed(
        {
            "id": "casier",
            "event_type": "casier.sanction.created",
            "username": "Ines",
            "details": {"member_id": "5550001", "member_username": "pixel_renard", "casier_id": "c1"},
        },
        {
            "id": "projet",
            "event_type": "project.created",
            "username": "Leo",
            "details": {"project_id": "p1", "title": "Soirée Pixel Art"},
        },
        {
            "id": "modif",
            "event_type": "project.details.updated",
            "username": "Leo",
            "details": {"project_id": "p1", "before": {"title": "Ancien nom"}, "after": {"title": "Nouveau nom"}},
        },
        {"id": "autre", "event_type": "project.created", "username": "Zoe", "details": {"title": "Rien"}},
    )
    assert _ids(_get(q="pixel_renard")) == ["casier"]
    assert _ids(_get(q="5550001")) == ["casier"]
    assert sorted(_ids(_get(q="pixel"))) == ["casier", "projet"]
    assert _ids(_get(q="nouveau nom")) == ["modif"]
    assert _ids(_get(q="ancien")) == ["modif"]


def test_q_special_characters_are_literal():
    _seed(
        {"id": "dot", "event_type": "auth.login.success", "username": "a.b"},
        {"id": "plain", "event_type": "auth.login.success", "username": "axb"},
        {"id": "star", "event_type": "casier.created", "details": {"member_username": "x*y(z)[1]+?"}},
        {"id": "slash", "event_type": "casier.created", "details": {"member_username": "back\\slash"}},
    )
    assert _ids(_get(q="a.b")) == ["dot"]
    assert _ids(_get(q=".*")) == []
    assert _ids(_get(q="x*y(z)[1]+?")) == ["star"]
    for dangerous in ("(", ")", "[", "*", "+", "?", "\\", "$", "^", "|", "{2}", "(?i)"):
        response = _get(q=dangerous)
        assert response.status_code == 200, dangerous
    assert _ids(_get(q="back\\slash")) == ["slash"]
    assert _ids(_get(q="(")) == ["star"]


def test_blank_q_is_ignored():
    _seed({"id": "a", "event_type": "auth.logout"}, {"id": "b", "event_type": "auth.logout"})
    assert _get(q="   ").json()["total"] == 2


# --- Catégories -------------------------------------------------------------------------------------

CATEGORY_SAMPLES = {
    "login_started": "auth.login.started",
    "login_success": "auth.login.success",
    "login_failure": "auth.login.failure",
    "logout": "auth.logout",
    "session_invalid": "auth.session.invalid",
    "session_check": "auth.session.check_failed",
    "forbidden": "authz.forbidden",
    "casier": "casier.created",
    "casier_note": "casier.sanction.note.created",
    "project": "project.created",
    "project_task": "project.task.validated",
    "agenda": "agenda.settings.updated",
    "inconnu": "truc.bidule",
}


def _seed_samples() -> None:
    _seed(*({"id": key, "event_type": event_type} for key, event_type in CATEGORY_SAMPLES.items()))


def test_category_connexions():
    _seed_samples()
    assert sorted(_ids(_get(categories="connexions"))) == sorted(
        ["login_started", "login_success", "login_failure", "logout", "session_invalid", "session_check"]
    )


def test_category_acces_refuses_includes_login_failures():
    _seed_samples()
    assert sorted(_ids(_get(categories="acces_refuses"))) == ["forbidden", "login_failure"]


def test_category_casiers_and_projets():
    _seed_samples()
    assert sorted(_ids(_get(categories="casiers"))) == ["casier", "casier_note"]
    assert sorted(_ids(_get(categories="projets"))) == ["project", "project_task"]


def test_category_autres_is_everything_else():
    _seed_samples()
    assert sorted(_ids(_get(categories="autres"))) == ["agenda", "inconnu"]


def test_categories_multi_select_is_a_union():
    _seed_samples()
    assert sorted(_ids(_get(categories="casiers,projets"))) == sorted(
        ["casier", "casier_note", "project", "project_task"]
    )
    assert sorted(_ids(_get(categories="acces_refuses, autres"))) == sorted(
        ["forbidden", "login_failure", "agenda", "inconnu"]
    )
    assert _get(categories="connexions,acces_refuses,casiers,projets,autres").json()["total"] == len(CATEGORY_SAMPLES)


def test_categories_blank_ignored_unknown_rejected():
    _seed_samples()
    assert _get(categories="").json()["total"] == len(CATEGORY_SAMPLES)
    assert _get(categories=" , ").json()["total"] == len(CATEGORY_SAMPLES)
    assert _get(categories="casiers,,casiers").json()["total"] == 2
    assert _get(categories="casiers,inconnue").status_code == 422
    assert _get(categories="auth.login.success").status_code == 422


def test_categories_combined_with_legacy_event_type():
    _seed_samples()
    assert _ids(_get(categories="casiers", event_type="casier.created")) == ["casier"]
    assert _ids(_get(categories="projets", event_type="casier.created")) == []


# --- Période (jour calendaire Europe/Paris, bornes incluses) ----------------------------------------


def test_date_range_uses_paris_days_in_winter():
    # CET (UTC+1) : le 15 mars à Paris commence le 14 mars à 23:00 UTC.
    _seed(
        {"id": "avant", "event_type": "auth.logout", "created_at": datetime(2026, 3, 14, 22, 59, tzinfo=UTC)},
        {"id": "debut", "event_type": "auth.logout", "created_at": datetime(2026, 3, 14, 23, 0, tzinfo=UTC)},
        {"id": "fin", "event_type": "auth.logout", "created_at": datetime(2026, 3, 15, 22, 59, tzinfo=UTC)},
        {"id": "apres", "event_type": "auth.logout", "created_at": datetime(2026, 3, 15, 23, 0, tzinfo=UTC)},
    )
    assert sorted(_ids(_get(date_from="2026-03-15", date_to="2026-03-15"))) == ["debut", "fin"]
    assert sorted(_ids(_get(date_from="2026-03-15"))) == ["apres", "debut", "fin"]
    assert sorted(_ids(_get(date_to="2026-03-15"))) == ["avant", "debut", "fin"]


def test_date_range_uses_paris_days_in_summer():
    # CEST (UTC+2) : le 15 juillet à Paris commence le 14 juillet à 22:00 UTC.
    _seed(
        {"id": "avant", "event_type": "auth.logout", "created_at": datetime(2026, 7, 14, 21, 59, tzinfo=UTC)},
        {"id": "debut", "event_type": "auth.logout", "created_at": datetime(2026, 7, 14, 22, 0, tzinfo=UTC)},
        {"id": "fin", "event_type": "auth.logout", "created_at": datetime(2026, 7, 15, 21, 59, tzinfo=UTC)},
        {"id": "apres", "event_type": "auth.logout", "created_at": datetime(2026, 7, 15, 22, 0, tzinfo=UTC)},
    )
    assert sorted(_ids(_get(date_from="2026-07-15", date_to="2026-07-15"))) == ["debut", "fin"]


def test_date_range_multiple_days_is_inclusive_across_dst_change():
    # Passage à l'heure d'été le 29 mars 2026 : ce jour-là ne dure que 23 h.
    _seed(
        {"id": "veille", "event_type": "auth.logout", "created_at": datetime(2026, 3, 28, 22, 59, tzinfo=UTC)},
        {"id": "jour", "event_type": "auth.logout", "created_at": datetime(2026, 3, 28, 23, 0, tzinfo=UTC)},
        {"id": "dernier", "event_type": "auth.logout", "created_at": datetime(2026, 3, 29, 21, 59, tzinfo=UTC)},
        {"id": "lendemain", "event_type": "auth.logout", "created_at": datetime(2026, 3, 29, 22, 0, tzinfo=UTC)},
    )
    assert sorted(_ids(_get(date_from="2026-03-29", date_to="2026-03-29"))) == ["dernier", "jour"]
    assert sorted(_ids(_get(date_from="2026-03-29", date_to="2026-03-30"))) == ["dernier", "jour", "lendemain"]


@pytest.mark.parametrize(
    "params",
    [
        {"date_from": "15/03/2026"},
        {"date_to": "2026-3-5"},
        {"date_from": "20260315"},
        {"date_from": "2026-02-30"},
        {"date_to": "2026-13-01"},
        {"date_from": "0001-01-01"},
        {"date_to": "2101-01-01"},
        {"date_from": "2026-03-16", "date_to": "2026-03-15"},
    ],
)
def test_invalid_dates_are_rejected_with_422(params):
    assert _get(**params).status_code == 422


# --- Filtres combinés ---------------------------------------------------------------------------------


def test_combined_q_categories_and_dates():
    day = datetime(2026, 3, 15, 10, 0, tzinfo=UTC)
    _seed(
        {"id": "ok", "event_type": "casier.sanction.created", "username": "Ines", "created_at": day,
         "details": {"member_username": "pixel_renard"}},
        {"id": "mauvais-membre", "event_type": "casier.sanction.created", "username": "Ines", "created_at": day,
         "details": {"member_username": "autre"}},
        {"id": "mauvaise-categorie", "event_type": "project.created", "username": "Ines", "created_at": day,
         "details": {"title": "pixel"}},
        {"id": "mauvais-jour", "event_type": "casier.sanction.created", "username": "Ines",
         "created_at": day + timedelta(days=3), "details": {"member_username": "pixel_renard"}},
    )
    response = _get(q="pixel", categories="casiers", date_from="2026-03-15", date_to="2026-03-16")
    assert _ids(response) == ["ok"]
    assert response.json()["total"] == 1

    response = _get(q="ines", categories="casiers,projets", date_from="2026-03-15", date_to="2026-03-15",
                    helper_id="")
    assert sorted(_ids(response)) == ["mauvais-membre", "mauvaise-categorie", "ok"]


def test_combined_filters_keep_pagination_total():
    _seed(*({"id": f"c{i}", "event_type": "casier.created", "username": "Ines"} for i in range(5)),
          {"id": "x", "event_type": "auth.logout", "username": "Ines"})
    response = _get(q="ines", categories="casiers", limit=2, skip=2)
    body = response.json()
    assert body["total"] == 5
    assert [item["id"] for item in body["items"]] == ["c2", "c1"]


# --- Résumé du jour -------------------------------------------------------------------------------------


def _paris_today_start_utc() -> datetime:
    now = datetime.now(PARIS)
    return datetime(now.year, now.month, now.day, tzinfo=PARIS).astimezone(UTC)


def test_summary_counts_today_paris_only():
    start = _paris_today_start_utc()
    inside = start + timedelta(minutes=1)
    yesterday = start - timedelta(minutes=1)
    tomorrow = start + timedelta(days=1)
    _seed(
        {"event_type": "authz.forbidden", "created_at": inside},
        {"event_type": "authz.forbidden", "created_at": start},
        {"event_type": "authz.forbidden", "created_at": yesterday},
        {"event_type": "auth.login.success", "created_at": inside},
        {"event_type": "auth.login.success", "created_at": inside},
        {"event_type": "auth.login.success", "created_at": tomorrow},
        {"event_type": "auth.login.failure", "created_at": inside},
        {"event_type": "auth.login.started", "created_at": inside},
        {"event_type": "casier.created", "created_at": inside},
        {"event_type": "casier.sanction.created", "created_at": inside},
        {"event_type": "casier.fiche_s.closed", "created_at": inside},
        {"event_type": "casier.created", "created_at": yesterday},
        {"event_type": "project.created", "created_at": inside},
    )
    response = _get("/api/responsable/auth-logs/summary")
    assert response.status_code == 200
    assert response.json() == {
        "date": datetime.now(PARIS).date().isoformat(),
        "access_denied": 2,
        "login_success": 2,
        "login_failure": 1,
        "casier_changes": 3,
    }


def test_summary_is_zero_without_logs():
    body = _get("/api/responsable/auth-logs/summary").json()
    assert (body["access_denied"], body["login_success"], body["login_failure"], body["casier_changes"]) == (0, 0, 0, 0)
