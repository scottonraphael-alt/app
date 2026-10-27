"""Tests hors ligne de la fondation agenda : heure de Paris (changements d'heure compris),
réglages des rappels (environnement relu à chaque appel, document agenda_settings/global) et modèles.

Lancer depuis backend/ : python -m pytest -q -p no:cacheprovider -n 0 tests/test_agenda_time.py
"""
import security_harness as h  # noqa: I001  (doit être importé en premier)

import logging
from datetime import date, datetime, time, timedelta, timezone

import httpx
import pytest
from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError
from starlette.requests import Request

import config
from models import staff as models
from models.ticket import AuthenticatedHelper
from services import agenda_settings, agenda_time

AGENDA_ENV = (
    "AGENDA_REMINDERS_ENABLED",
    "DISCORD_AGENDA_CHANNEL_ID",
    "DISCORD_AGENDA_PING_ROLE_ID",
    "AGENDA_DAY_REMINDER_TIME",
    "AGENDA_REMINDER_POLL_SECONDS",
    "FRONTEND_URL",
)
CHANNEL_ID = "500000000000000001"
OTHER_CHANNEL_ID = "500000000000000002"
PING_ROLE_ID = "300000000000000003"
FROZEN_NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
_REAL_NOW_UTC = agenda_time.now_utc


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    h.reset_db()
    h.reset_discord()
    agenda_settings.reset_state()
    for name in AGENDA_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(agenda_time, "now_utc", lambda: FROZEN_NOW)
    yield
    agenda_settings.reset_state()


def _freeze(monkeypatch, moment: datetime) -> None:
    monkeypatch.setattr(agenda_time, "now_utc", lambda: moment)


def _utc(*parts) -> datetime:
    return datetime(*parts, tzinfo=timezone.utc)


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "PUT",
        "path": "/api/agenda/settings",
        "headers": [(b"user-agent", b"pytest")],
        "query_string": b"",
        "client": ("203.0.113.7", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
    })


def _responsable() -> AuthenticatedHelper:
    return AuthenticatedHelper(id=h.USER_IDS["responsable"], username="test-responsable", global_name="Lou")


def _insert_settings(doc: dict) -> None:
    h.run(h.db.agenda_settings.insert_one({"_id": "global", **doc}))


def _settings_doc() -> dict | None:
    return h.run(h.db.agenda_settings.find_one({"_id": "global"}))


def _update(payload: dict) -> agenda_settings.EffectiveSettings:
    model = models.AgendaSettingsIn.model_validate(payload)
    return h.run(agenda_settings.update_settings(model, _responsable(), _request()))


def _http_error(call) -> HTTPException:
    with pytest.raises(HTTPException) as excinfo:
        call()
    return excinfo.value


# ---------------------------------------------------------------------------
# Heure de Paris
# ---------------------------------------------------------------------------

def test_now_utc_is_aware_utc():
    now = _REAL_NOW_UTC()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_frozen_now_drives_every_helper(monkeypatch):
    # Les fonctions du module appellent now_utc() par le module : le gel des tests s'applique partout.
    assert agenda_time.today_paris() == "2026-10-25"
    assert agenda_time.today_paris_date() == date(2026, 10, 25)
    assert agenda_time.current_time_paris() == "13:00"  # heure d'hiver depuis 03:00
    assert agenda_time.now_iso() == "2026-10-25T12:00:00+00:00"
    assert agenda_time.now_paris().utcoffset() == timedelta(hours=1)


@pytest.mark.parametrize(
    ("moment", "expected_day", "expected_time"),
    [
        (_utc(2026, 10, 24, 21, 59), "2026-10-24", "23:59"),  # heure d'été (+2)
        (_utc(2026, 10, 24, 22, 30), "2026-10-25", "00:30"),  # déjà le 25 à Paris
        (_utc(2026, 10, 25, 0, 30), "2026-10-25", "02:30"),   # 02:30 en heure d'été (première fois)
        (_utc(2026, 10, 25, 1, 30), "2026-10-25", "02:30"),   # 02:30 en heure d'hiver (seconde fois)
        (_utc(2026, 12, 31, 23, 30), "2027-01-01", "00:30"),  # heure d'hiver (+1), changement d'année
        (_utc(2026, 3, 29, 0, 59), "2026-03-29", "01:59"),
        (_utc(2026, 3, 29, 1, 0), "2026-03-29", "03:00"),     # 02:00 n'existe pas à Paris
    ],
)
def test_today_and_time_in_paris(monkeypatch, moment, expected_day, expected_time):
    _freeze(monkeypatch, moment)
    assert agenda_time.today_paris() == expected_day
    assert agenda_time.current_time_paris() == expected_time


def test_as_utc_reads_naive_as_utc():
    naive = datetime(2026, 10, 25, 19, 0)
    assert agenda_time.as_utc(naive) == _utc(2026, 10, 25, 19, 0)
    assert agenda_time.as_utc(naive).tzinfo is not None
    paris = datetime(2026, 10, 25, 20, 0, tzinfo=agenda_time.PARIS)
    assert agenda_time.as_utc(paris) == _utc(2026, 10, 25, 19, 0)
    assert agenda_time.as_utc(paris).utcoffset() == timedelta(0)
    assert agenda_time.as_utc("2026-10-25T19:00:00Z") == _utc(2026, 10, 25, 19, 0)
    assert agenda_time.as_utc("2026-10-25T21:00:00+02:00") == _utc(2026, 10, 25, 19, 0)
    assert agenda_time.as_utc("2026-10-25T19:00:00") == _utc(2026, 10, 25, 19, 0)
    assert agenda_time.as_utc(None) is None
    assert agenda_time.as_utc("") is None
    with pytest.raises(TypeError):
        agenda_time.as_utc(date(2026, 10, 25))


def test_naive_and_aware_compare_after_as_utc():
    # Motor et mongomock renvoient des datetime naïfs : comparer sans as_utc lèverait TypeError.
    stored = datetime(2026, 10, 25, 11, 0)
    with pytest.raises(TypeError):
        _ = stored < FROZEN_NOW
    assert agenda_time.as_utc(stored) < FROZEN_NOW


def test_iso_z_and_unix_seconds():
    assert agenda_time.iso_z(_utc(2026, 10, 25, 19, 0, 5, 123456)) == "2026-10-25T19:00:05Z"
    assert agenda_time.iso_z(datetime(2026, 10, 25, 19, 0)) == "2026-10-25T19:00:00Z"
    assert agenda_time.iso_z(datetime(2026, 10, 25, 21, 0, tzinfo=agenda_time.PARIS)) == "2026-10-25T20:00:00Z"
    assert agenda_time.iso_z(None) is None
    assert agenda_time.unix_seconds(_utc(1970, 1, 1, 0, 1)) == 60
    assert agenda_time.unix_seconds(datetime(1970, 1, 1, 0, 1)) == 60
    # Minuit à Paris (horodatage Discord d'une journée entière) le jour du passage à l'heure d'hiver.
    assert agenda_time.unix_seconds(agenda_time.local_start("2026-10-25")) == int(_utc(2026, 10, 24, 22, 0).timestamp())


@pytest.mark.parametrize("value", ["2026-10-25", "2028-02-29", "2026-01-01"])
def test_parse_date_accepts_real_dates(value):
    assert agenda_time.parse_date(value) == date.fromisoformat(value)
    assert agenda_time.is_date_str(value)


@pytest.mark.parametrize(
    "value",
    ["2026-02-30", "2027-02-29", "2026-13-01", "20261025", "2026-1-5", " 2026-10-25", "2026-10-25T10:00",
     "٢٠٢٦-١٠-٢٥", "", None, 20261025],
)
def test_parse_date_is_strict(value):
    assert not agenda_time.is_date_str(value)
    with pytest.raises(ValueError):
        agenda_time.parse_date(value)


def test_parse_time_is_strict():
    assert agenda_time.parse_time("00:00") == time(0, 0)
    assert agenda_time.parse_time("23:59") == time(23, 59)
    assert agenda_time.parse_time("09:05") == time(9, 5)
    for value in ("24:00", "9:00", "09:60", "09:00:00", "0900", "١٢:٠٠", "1٢:3٠", "12:30\n", "", None):
        assert not agenda_time.is_time_str(value)
        with pytest.raises(ValueError):
            agenda_time.parse_time(value)


def test_add_days_and_days_between():
    assert agenda_time.add_days("2026-10-25", 1) == "2026-10-26"
    assert agenda_time.add_days("2026-10-25", -1) == "2026-10-24"
    assert agenda_time.add_days("2026-12-31", 1) == "2027-01-01"
    assert agenda_time.add_days("2028-02-28", 1) == "2028-02-29"
    assert agenda_time.add_days("2026-10-25", 92) == "2027-01-25"
    assert agenda_time.days_between("2026-10-20", "2026-10-30") == 10
    assert agenda_time.days_between("2026-10-30", "2026-10-20") == -10
    # Un jour de 25 h (passage à l'heure d'hiver) compte pour un jour.
    assert agenda_time.days_between("2026-10-24", "2026-10-26") == 2


def test_date_in_bounds_uses_paris_today(monkeypatch):
    assert agenda_time.date_in_bounds("2025-10-24")       # today - 366 j
    assert not agenda_time.date_in_bounds("2025-10-23")
    assert agenda_time.date_in_bounds("2028-10-25")       # today + 731 j (2028 est bissextile)
    assert not agenda_time.date_in_bounds("2028-10-26")
    assert agenda_time.date_in_bounds("2026-10-26", past_days=0, future_days=1)
    assert not agenda_time.date_in_bounds("2026-10-24", past_days=0, future_days=1)
    assert agenda_time.date_in_bounds("2026-01-02", past_days=1, future_days=1, today="2026-01-01")
    # 23:30 UTC le 31 décembre = 1er janvier à Paris : la borne suit la date de Paris.
    _freeze(monkeypatch, _utc(2026, 12, 31, 23, 30))
    assert agenda_time.date_in_bounds("2027-01-01", past_days=0, future_days=0)
    assert not agenda_time.date_in_bounds("2026-12-31", past_days=0, future_days=0)


def test_local_start_offsets_and_midnight():
    winter = agenda_time.local_start("2026-10-26", "20:00")
    summer = agenda_time.local_start("2026-10-24", "20:00")
    assert winter.utcoffset() == timedelta(hours=1)
    assert summer.utcoffset() == timedelta(hours=2)
    assert (winter.hour, winter.minute) == (20, 0)
    midnight = agenda_time.local_start("2026-10-29")
    assert (midnight.hour, midnight.minute) == (0, 0)
    assert midnight.tzinfo is agenda_time.PARIS
    assert agenda_time.start_utc("2026-10-29") == _utc(2026, 10, 28, 23, 0)
    assert agenda_time.start_utc("2026-07-14") == _utc(2026, 7, 13, 22, 0)
    with pytest.raises(ValueError):
        agenda_time.local_start("2026-10-29", "25:00")
    with pytest.raises(ValueError):
        agenda_time.local_start("2026-02-30")


@pytest.mark.parametrize(
    ("day", "hour", "expected"),
    [
        ("2026-10-24", "20:00", _utc(2026, 10, 24, 18, 0)),  # veille du changement : +2
        ("2026-10-25", "20:00", _utc(2026, 10, 25, 19, 0)),  # jour du changement, après 03:00 : +1
        ("2026-10-26", "20:00", _utc(2026, 10, 26, 19, 0)),
        ("2026-03-28", "20:00", _utc(2026, 3, 28, 19, 0)),
        ("2026-03-29", "20:00", _utc(2026, 3, 29, 18, 0)),   # passage à l'heure d'été
        ("2026-10-27", "00:30", _utc(2026, 10, 26, 23, 30)),
    ],
)
def test_start_utc_across_dst(day, hour, expected):
    assert agenda_time.start_utc(day, hour) == expected
    assert agenda_time.start_utc(day, hour).utcoffset() == timedelta(0)


def test_dst_gap_and_ambiguous_wall_times():
    # 02:30 le 29 mars 2026 n'existe pas : lu avec le décalage d'avant (+1), soit 03:30 heure d'été.
    gap = agenda_time.start_utc("2026-03-29", "02:30")
    assert gap == _utc(2026, 3, 29, 1, 30)
    assert gap.astimezone(agenda_time.PARIS).strftime("%H:%M") == "03:30"
    # 02:30 le 25 octobre 2026 existe deux fois : première occurrence (heure d'été).
    assert agenda_time.start_utc("2026-10-25", "02:30") == _utc(2026, 10, 25, 0, 30)


def test_reminder_due_dates_spec_example_across_dst():
    # Réunion le 2026-10-26 à 20:00 (lendemain du passage à l'heure d'hiver), exemple de la spec.
    event = agenda_time.start_utc("2026-10-26", "20:00")
    assert event == _utc(2026, 10, 26, 19, 0)
    assert agenda_time.wall_days_before_utc("2026-10-26", "20:00", 7) == _utc(2026, 10, 19, 18, 0)
    assert agenda_time.wall_days_before_utc("2026-10-26", "20:00", 2) == _utc(2026, 10, 24, 18, 0)
    assert agenda_time.wall_days_before_utc("2026-10-26", "20:00", 1) == _utc(2026, 10, 25, 19, 0)
    assert event - timedelta(hours=1) == _utc(2026, 10, 26, 18, 0)  # H-1 sur l'instant UTC
    # Le même calcul en UTC pur serait faux d'une heure : c'est ce que wall_days_before_utc évite.
    assert event - timedelta(days=2) != agenda_time.wall_days_before_utc("2026-10-26", "20:00", 2)
    # Arithmétique aware de Python sur l'heure murale : même résultat.
    local = agenda_time.local_start("2026-10-26", "20:00")
    assert (local - timedelta(days=2)).astimezone(timezone.utc) == _utc(2026, 10, 24, 18, 0)


def test_reminder_due_dates_spring_forward_and_all_day():
    assert agenda_time.wall_days_before_utc("2026-03-30", "09:00", 1) == _utc(2026, 3, 29, 7, 0)
    assert agenda_time.wall_days_before_utc("2026-03-30", "09:00", 2) == _utc(2026, 3, 28, 8, 0)
    # Entrée sur la journée le 2026-10-27, J-1 à 10:00 heure de Paris = 09:00Z (heure d'hiver).
    assert agenda_time.wall_days_before_utc("2026-10-27", "10:00", 1) == _utc(2026, 10, 26, 9, 0)
    # Entrée le 2026-10-27 à 00:30 : J-1 = 2026-10-25T23:30Z, J-2 déjà passé à 12:00Z le 25.
    assert agenda_time.wall_days_before_utc("2026-10-27", "00:30", 1) == _utc(2026, 10, 25, 23, 30)
    assert agenda_time.wall_days_before_utc("2026-10-27", "00:30", 2) < FROZEN_NOW
    assert agenda_time.wall_days_before_utc("2026-10-29", None, 0) == agenda_time.start_utc("2026-10-29")


def test_to_paris():
    assert agenda_time.to_paris(None) is None
    converted = agenda_time.to_paris(datetime(2026, 10, 25, 19, 0))
    assert converted.utcoffset() == timedelta(hours=1)
    assert converted.strftime("%Y-%m-%d %H:%M") == "2026-10-25 20:00"


def test_model_and_time_patterns_agree():
    dates = ["2026-10-25", "2026-02-30", "20261025", "٢٠٢٦-١٠-٢٥", "2028-02-29", "2026-10-25\n"]
    times = ["00:00", "23:59", "24:00", "9:00", "١٢:٠٠", "1٢:3٠", "12:30\n"]
    date_adapter = TypeAdapter(models.DateStr)
    time_adapter = TypeAdapter(models.TimeStr)

    def accepted(adapter, value):
        try:
            adapter.validate_python(value)
            return True
        except ValidationError:
            return False

    for value in dates:
        assert accepted(date_adapter, value) == agenda_time.is_date_str(value), value
    for value in times:
        assert accepted(time_adapter, value) == agenda_time.is_time_str(value), value


# ---------------------------------------------------------------------------
# Réglages : environnement
# ---------------------------------------------------------------------------

def test_defaults_without_env_or_document():
    settings = h.run(agenda_settings.get_settings())
    assert settings.enabled is True
    assert settings.disabled_by_env is False
    assert settings.channel_id is None
    assert settings.ping_role_id is None
    assert settings.day_reminder_time == "10:00"
    assert settings.poll_seconds == 30
    assert settings.frontend_url == "https://iris.loasis.app"
    assert settings.source == "env"
    assert settings.timezone == "Europe/Paris"
    assert settings.default_offsets == ["J-7", "J-2", "J-1", "H-1"]
    assert agenda_settings.is_configured(settings) is False


def test_env_is_read_at_each_call(monkeypatch):
    monkeypatch.setenv("DISCORD_AGENDA_CHANNEL_ID", CHANNEL_ID)
    monkeypatch.setenv("DISCORD_AGENDA_PING_ROLE_ID", PING_ROLE_ID)
    monkeypatch.setenv("AGENDA_DAY_REMINDER_TIME", "09:30")
    monkeypatch.setenv("AGENDA_REMINDER_POLL_SECONDS", "45")
    monkeypatch.setenv("FRONTEND_URL", "https://preprod.example/")
    settings = h.run(agenda_settings.get_settings())
    assert settings.channel_id == CHANNEL_ID
    assert settings.ping_role_id == PING_ROLE_ID
    assert settings.day_reminder_time == "09:30"
    assert settings.poll_seconds == 45
    assert settings.frontend_url == "https://preprod.example"
    assert agenda_settings.frontend_url() == "https://preprod.example"
    assert agenda_settings.is_configured(settings) is True

    monkeypatch.delenv("DISCORD_AGENDA_CHANNEL_ID")
    monkeypatch.setenv("AGENDA_REMINDER_POLL_SECONDS", "60")
    settings = h.run(agenda_settings.get_settings())
    assert settings.channel_id is None
    assert settings.poll_seconds == 60
    assert agenda_settings.is_configured(settings) is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("", True), ("true", True), ("1", True), ("yes", True), ("oui", True), (" ON ", True), ("True", True),
     ("false", False), ("0", False), ("non", False), ("off", False), ("désactivé", False)],
)
def test_env_master_switch_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("AGENDA_REMINDERS_ENABLED", raw)
    assert agenda_settings.env_enabled() is expected
    settings = h.run(agenda_settings.get_settings())
    assert settings.enabled is expected
    assert settings.disabled_by_env is (not expected)


def test_invalid_env_values_fall_back(monkeypatch):
    monkeypatch.setenv("DISCORD_AGENDA_CHANNEL_ID", "salon-staff")
    monkeypatch.setenv("DISCORD_AGENDA_PING_ROLE_ID", "12345")
    monkeypatch.setenv("AGENDA_DAY_REMINDER_TIME", "25:00")
    monkeypatch.setenv("AGENDA_REMINDER_POLL_SECONDS", "2")
    settings = h.run(agenda_settings.get_settings())
    assert settings.channel_id is None
    assert settings.ping_role_id is None
    assert settings.day_reminder_time == "10:00"
    assert settings.poll_seconds == 5  # 5 s minimum
    monkeypatch.setenv("AGENDA_REMINDER_POLL_SECONDS", "trente")
    assert agenda_settings.poll_seconds() == 30


# ---------------------------------------------------------------------------
# Réglages : document agenda_settings/global
# ---------------------------------------------------------------------------

def test_document_overrides_env_field_by_field(monkeypatch):
    monkeypatch.setenv("DISCORD_AGENDA_CHANNEL_ID", CHANNEL_ID)
    monkeypatch.setenv("AGENDA_DAY_REMINDER_TIME", "09:00")
    _insert_settings({"ping_role_id": PING_ROLE_ID, "updated_by": {"id": "1", "username": "lou"},
                      "updated_at": "2026-10-25T10:00:00+00:00"})
    settings = h.run(agenda_settings.get_settings())
    assert settings.source == "db"
    assert settings.channel_id == CHANNEL_ID  # absent du document : environnement
    assert settings.ping_role_id == PING_ROLE_ID
    assert settings.day_reminder_time == "09:00"
    assert settings.enabled is True
    assert settings.updated_by == {"id": "1", "username": "lou"}

    h.run(h.db.agenda_settings.update_one(
        {"_id": "global"}, {"$set": {"channel_id": None, "day_reminder_time": "08:15"}}
    ))
    settings = h.run(agenda_settings.get_settings())
    assert settings.channel_id is None  # null en base : efface la valeur de l'environnement
    assert settings.day_reminder_time == "08:15"
    assert agenda_settings.is_configured(settings) is False


def test_document_with_invalid_values_is_tolerated(monkeypatch):
    monkeypatch.setenv("AGENDA_DAY_REMINDER_TIME", "09:00")
    _insert_settings({"enabled": "oui", "channel_id": "pas-un-id", "day_reminder_time": "midi"})
    settings = h.run(agenda_settings.get_settings())
    assert settings.enabled is True
    assert settings.channel_id is None
    assert settings.day_reminder_time == "09:00"


def test_env_kill_switch_wins_over_document(monkeypatch):
    _insert_settings({"enabled": True, "channel_id": CHANNEL_ID})
    settings = h.run(agenda_settings.get_settings())
    assert settings.enabled is True
    assert agenda_settings.is_configured(settings) is True

    monkeypatch.setenv("AGENDA_REMINDERS_ENABLED", "false")
    settings = h.run(agenda_settings.get_settings())
    assert settings.enabled is False
    assert settings.disabled_by_env is True
    assert settings.db_enabled is True
    assert agenda_settings.is_configured(settings) is False


def test_document_can_disable_but_not_enable(monkeypatch):
    _insert_settings({"enabled": False, "channel_id": CHANNEL_ID})
    settings = h.run(agenda_settings.get_settings())
    assert settings.enabled is False
    assert settings.disabled_by_env is False
    assert agenda_settings.is_configured(settings) is False


def test_is_configured_requires_bot_token(monkeypatch):
    settings = agenda_settings.EffectiveSettings(channel_id=CHANNEL_ID)
    assert agenda_settings.is_configured(settings) is True
    monkeypatch.setattr(config, "DISCORD_BOT_TOKEN", "")
    assert agenda_settings.is_configured(settings) is False
    assert agenda_settings.inactive_reason(settings) == "Rappels agenda inactifs : DISCORD_BOT_TOKEN non défini."


def test_idle_message_logged_once(caplog):
    caplog.set_level(logging.INFO, logger="services.agenda_settings")
    idle = agenda_settings.EffectiveSettings()
    assert agenda_settings.inactive_reason(idle) == "Rappels agenda inactifs : DISCORD_AGENDA_CHANNEL_ID non défini."
    assert agenda_settings.log_idle_once(idle) is True
    assert agenda_settings.log_idle_once(idle) is False
    messages = [record.getMessage() for record in caplog.records]
    assert messages.count("Rappels agenda inactifs : DISCORD_AGENDA_CHANNEL_ID non défini.") == 1

    assert agenda_settings.log_idle_once(agenda_settings.EffectiveSettings(channel_id=CHANNEL_ID)) is False
    assert agenda_settings.log_idle_once(idle) is True  # de nouveau inactif après une configuration
    agenda_settings.reset_state()
    assert agenda_settings.log_idle_once(idle) is True


def test_ensure_test_allowed():
    error = _http_error(lambda: agenda_settings.ensure_test_allowed(
        agenda_settings.EffectiveSettings(enabled=False, env_enabled=False, disabled_by_env=True, channel_id=CHANNEL_ID)
    ))
    assert (error.status_code, error.detail) == (409, "Rappels désactivés par la configuration du serveur.")
    error = _http_error(lambda: agenda_settings.ensure_test_allowed(agenda_settings.EffectiveSettings()))
    assert (error.status_code, error.detail) == (409, "Rappels non configurés : choisissez un salon.")
    # Seul l'interrupteur de la base est coupé : le test reste permis.
    agenda_settings.ensure_test_allowed(
        agenda_settings.EffectiveSettings(enabled=False, db_enabled=False, channel_id=CHANNEL_ID)
    )


# ---------------------------------------------------------------------------
# Réglages : salon Discord
# ---------------------------------------------------------------------------

def test_channel_visibility():
    everyone_denied = {"permission_overwrites": [{"id": h.GUILD_ID, "type": 0, "allow": "0", "deny": "1024"}]}
    assert agenda_settings.channel_visibility(everyone_denied) == "staff"
    everyone_allowed = {"permission_overwrites": [{"id": h.GUILD_ID, "type": 0, "allow": "1024", "deny": "0"}]}
    assert agenda_settings.channel_visibility(everyone_allowed) == "public"
    other_role_only = {"permission_overwrites": [{"id": "300000000000000003", "type": 0, "allow": "1024", "deny": "0"}]}
    assert agenda_settings.channel_visibility(other_role_only) == "public"
    assert agenda_settings.channel_visibility({"permission_overwrites": []}) == "public"
    assert agenda_settings.channel_visibility({}) == "inconnu"
    broken = {"permission_overwrites": [{"id": h.GUILD_ID, "deny": "beaucoup"}]}
    assert agenda_settings.channel_visibility(broken) == "inconnu"
    combined = {"permission_overwrites": [{"id": h.GUILD_ID, "deny": str((1 << 10) | (1 << 11))}]}
    assert agenda_settings.channel_visibility(combined) == "staff"


def test_channel_info_without_channel_does_not_call_discord():
    info = h.run(agenda_settings.channel_info(None))
    assert info == {"name": None, "status": "non_configure", "visibility": "inconnu", "type": None}
    assert h.fake_discord.calls == []


def test_channel_info_ok_and_cached():
    h.fake_discord.add_channel(CHANNEL_ID, name="rappels-staff")
    h.fake_discord.channels[CHANNEL_ID]["permission_overwrites"] = [{"id": h.GUILD_ID, "deny": "1024"}]
    info = h.run(agenda_settings.channel_info(CHANNEL_ID))
    assert info == {"name": "rappels-staff", "status": "ok", "visibility": "staff", "type": 0}
    assert h.fake_discord.calls == [f"/channels/{CHANNEL_ID}"]

    h.fake_discord.channels[CHANNEL_ID]["name"] = "renomme"
    assert h.run(agenda_settings.channel_info(CHANNEL_ID))["name"] == "rappels-staff"  # cache de 600 s
    assert len(h.fake_discord.calls) == 1

    agenda_settings.reset_state()
    assert h.run(agenda_settings.channel_info(CHANNEL_ID))["name"] == "renomme"
    assert len(h.fake_discord.calls) == 2

    h.fake_discord.channels[CHANNEL_ID]["permission_overwrites"] = []
    assert h.run(agenda_settings.channel_info(CHANNEL_ID))["visibility"] == "staff"  # encore en cache
    assert h.run(agenda_settings.channel_info(CHANNEL_ID, force=True))["visibility"] == "public"
    assert h.run(agenda_settings.channel_info(CHANNEL_ID))["visibility"] == "public"
    assert len(h.fake_discord.calls) == 3


def test_channel_info_cache_expires(monkeypatch):
    h.fake_discord.add_channel(CHANNEL_ID, name="rappels-staff")
    clock = [1000.0]
    monkeypatch.setattr(agenda_settings.time, "monotonic", lambda: clock[0])
    h.run(agenda_settings.channel_info(CHANNEL_ID))
    clock[0] += agenda_settings.CHANNEL_CACHE_SECONDS - 1
    h.run(agenda_settings.channel_info(CHANNEL_ID))
    assert len(h.fake_discord.calls) == 1
    clock[0] += 2
    h.run(agenda_settings.channel_info(CHANNEL_ID))
    assert len(h.fake_discord.calls) == 2


def test_channel_info_never_raises():
    # Salon inconnu (404), d'un autre serveur (403), non textuel : jamais d'exception.
    assert h.run(agenda_settings.channel_info(CHANNEL_ID))["status"] == "inaccessible"

    agenda_settings.reset_state()
    h.fake_discord.add_channel(CHANNEL_ID, guild_id="100000000000000999")
    info = h.run(agenda_settings.channel_info(CHANNEL_ID))
    assert info == {"name": None, "status": "inaccessible", "visibility": "inconnu", "type": None}

    agenda_settings.reset_state()
    h.fake_discord.add_channel(CHANNEL_ID, name="vocal", channel_type=2)
    info = h.run(agenda_settings.channel_info(CHANNEL_ID))
    assert (info["status"], info["name"], info["type"]) == ("inaccessible", "vocal", 2)


def test_channel_info_network_error_is_inaccessible(monkeypatch):
    async def network_down(path, params=None):
        raise httpx.ConnectError("réseau coupé")

    h.fake_discord.add_channel(CHANNEL_ID, name="rappels-staff")
    monkeypatch.setattr(h.fake_discord, "get", network_down)
    assert h.run(agenda_settings.channel_info(CHANNEL_ID))["status"] == "inaccessible"


def test_channel_info_without_bot_configuration(monkeypatch):
    h.fake_discord.add_channel(CHANNEL_ID, name="rappels-staff")
    monkeypatch.setattr(config, "DISCORD_BOT_TOKEN", "")  # le constructeur de DiscordService lève 503
    assert h.run(agenda_settings.channel_info(CHANNEL_ID))["status"] == "inaccessible"
    assert h.fake_discord.calls == []


def test_channel_info_failure_cached_briefly(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(agenda_settings.time, "monotonic", lambda: clock[0])
    h.run(agenda_settings.channel_info(CHANNEL_ID))
    h.run(agenda_settings.channel_info(CHANNEL_ID))
    assert len(h.fake_discord.calls) == 1
    h.fake_discord.add_channel(CHANNEL_ID, name="rappels-staff")
    clock[0] += agenda_settings.CHANNEL_ERROR_CACHE_SECONDS + 1
    assert h.run(agenda_settings.channel_info(CHANNEL_ID))["status"] == "ok"


# ---------------------------------------------------------------------------
# Réglages : écriture (PUT /api/agenda/settings)
# ---------------------------------------------------------------------------

def test_update_settings_writes_document_and_logs():
    h.fake_discord.add_channel(CHANNEL_ID, name="rappels-staff", channel_type=0)
    settings = _update({"enabled": True, "channel_id": CHANNEL_ID, "ping_role_id": PING_ROLE_ID,
                        "day_reminder_time": "09:15"})
    assert settings.source == "db"
    assert settings.channel_id == CHANNEL_ID
    assert (settings.ping_role_id, settings.day_reminder_time) == (PING_ROLE_ID, "09:15")
    assert agenda_settings.is_configured(settings) is True

    doc = _settings_doc()
    assert doc["channel_id"] == CHANNEL_ID
    assert doc["enabled"] is True
    assert doc["updated_by"] == {"id": h.USER_IDS["responsable"], "username": "test-responsable",
                                 "display_name": "Lou", "avatar_url": None}
    assert doc["updated_at"] == "2026-10-25T12:00:00+00:00"

    log = h.run(h.db.auth_logs.find_one({"event_type": "agenda.settings.updated"}))
    assert log is not None
    assert log["helper_id"] == h.USER_IDS["responsable"]
    assert log["status_code"] == 200
    assert log["details"]["before"]["channel_id"] is None
    assert log["details"]["before"]["source"] == "env"
    assert log["details"]["after"]["channel_id"] == CHANNEL_ID
    assert log["details"]["after"]["day_reminder_time"] == "09:15"

    # Le salon validé est mis en cache : la réponse du PUT ne rappelle pas Discord.
    calls = len(h.fake_discord.calls)
    assert h.run(agenda_settings.channel_info(CHANNEL_ID))["name"] == "rappels-staff"
    assert len(h.fake_discord.calls) == calls


def test_update_settings_partial_and_null_semantics(monkeypatch):
    monkeypatch.setenv("DISCORD_AGENDA_CHANNEL_ID", CHANNEL_ID)
    monkeypatch.setenv("AGENDA_DAY_REMINDER_TIME", "09:00")

    settings = _update({"ping_role_id": PING_ROLE_ID})
    assert settings.channel_id == CHANNEL_ID  # champ absent : l'environnement reste utilisé
    assert settings.ping_role_id == PING_ROLE_ID
    assert h.fake_discord.calls == []  # aucun salon envoyé : pas de vérification Discord

    settings = _update({"enabled": False, "day_reminder_time": "11:00"})
    assert settings.enabled is False
    assert settings.ping_role_id == PING_ROLE_ID
    assert settings.day_reminder_time == "11:00"

    settings = _update({"enabled": None, "day_reminder_time": None})  # retour aux valeurs de l'environnement
    assert settings.enabled is True
    assert settings.day_reminder_time == "09:00"
    assert "enabled" not in _settings_doc()

    settings = _update({"channel_id": None, "ping_role_id": None})
    assert settings.channel_id is None  # null : efface, même si l'environnement définit un salon
    assert settings.ping_role_id is None
    assert agenda_settings.is_configured(settings) is False


def test_update_settings_accepts_plain_dict_validated():
    settings = h.run(agenda_settings.update_settings({"day_reminder_time": "07:45"}, _responsable(), _request()))
    assert settings.day_reminder_time == "07:45"
    with pytest.raises(ValidationError):
        h.run(agenda_settings.update_settings({"day_reminder_time": "midi"}, _responsable(), _request()))


def test_update_settings_enabled_true_kept_off_by_env(monkeypatch):
    monkeypatch.setenv("AGENDA_REMINDERS_ENABLED", "false")
    h.fake_discord.add_channel(CHANNEL_ID, channel_type=5)  # salon d'annonces : accepté
    settings = _update({"enabled": True, "channel_id": CHANNEL_ID})
    assert _settings_doc()["enabled"] is True  # valeur enregistrée…
    assert settings.enabled is False  # …mais l'environnement l'emporte
    assert settings.disabled_by_env is True


@pytest.mark.parametrize(("channel_type", "accepted"), [(0, True), (5, True), (2, False), (4, False), (15, False)])
def test_update_settings_channel_type(channel_type, accepted):
    h.fake_discord.add_channel(CHANNEL_ID, channel_type=channel_type)
    if accepted:
        assert _update({"channel_id": CHANNEL_ID}).channel_id == CHANNEL_ID
        return
    error = _http_error(lambda: _update({"channel_id": CHANNEL_ID}))
    assert (error.status_code, error.detail) == (422, "Choisissez un salon textuel.")
    assert _settings_doc() is None
    assert h.run(h.db.auth_logs.count_documents({})) == 0


def test_update_settings_rejects_unknown_or_foreign_channel():
    error = _http_error(lambda: _update({"channel_id": CHANNEL_ID}))
    assert (error.status_code, error.detail) == (422, "Salon introuvable ou hors du serveur.")
    h.fake_discord.add_channel(OTHER_CHANNEL_ID, guild_id="100000000000000999")
    error = _http_error(lambda: _update({"channel_id": OTHER_CHANNEL_ID}))
    assert (error.status_code, error.detail) == (422, "Salon introuvable ou hors du serveur.")
    assert _settings_doc() is None


def test_update_settings_discord_unavailable(monkeypatch):
    async def bad_gateway(path, params=None):
        raise HTTPException(status_code=502, detail="Discord n’a pas pu traiter la demande.")

    monkeypatch.setattr(h.fake_discord, "get", bad_gateway)
    error = _http_error(lambda: _update({"channel_id": CHANNEL_ID}))
    assert (error.status_code, error.detail) == (503, "Discord ne répond pas, réessayez.")

    async def network_down(path, params=None):
        raise httpx.ReadTimeout("délai dépassé")

    monkeypatch.setattr(h.fake_discord, "get", network_down)
    error = _http_error(lambda: _update({"channel_id": CHANNEL_ID}))
    assert (error.status_code, error.detail) == (503, "Discord ne répond pas, réessayez.")

    monkeypatch.setattr(config, "DISCORD_BOT_TOKEN", "")
    error = _http_error(lambda: _update({"channel_id": CHANNEL_ID}))
    assert (error.status_code, error.detail) == (503, "Discord ne répond pas, réessayez.")
    assert _settings_doc() is None


def test_settings_out_hides_ids_from_staff(monkeypatch):
    monkeypatch.setenv("DISCORD_AGENDA_CHANNEL_ID", CHANNEL_ID)
    monkeypatch.setenv("DISCORD_AGENDA_PING_ROLE_ID", PING_ROLE_ID)
    h.fake_discord.add_channel(CHANNEL_ID, name="rappels-staff")
    settings = h.run(agenda_settings.get_settings())

    staff_view = h.run(agenda_settings.settings_out(settings, is_responsable=False))
    h.fake_discord.channels[CHANNEL_ID]["name"] = "rappels-equipe"
    refreshed = h.run(agenda_settings.settings_out(settings, is_responsable=False, refresh_channel=True))
    assert refreshed["channel_name"] == "rappels-equipe"
    h.fake_discord.channels[CHANNEL_ID]["name"] = "rappels-staff"
    agenda_settings.reset_state()
    assert staff_view["channel_id"] is None
    assert staff_view["ping_role_id"] is None
    assert staff_view["ping_role_configured"] is True
    assert staff_view["channel_name"] == "rappels-staff"

    view = h.run(agenda_settings.settings_out(settings, is_responsable=True))
    assert view == {
        "enabled": True, "disabled_by_env": False, "configured": True, "channel_status": "ok",
        "channel_name": "rappels-staff", "channel_visibility": "inconnu", "channel_id": CHANNEL_ID,
        "ping_role_id": PING_ROLE_ID, "ping_role_configured": True, "day_reminder_time": "10:00",
        "default_offsets": ["J-7", "J-2", "J-1", "H-1"], "timezone": "Europe/Paris", "source": "env",
    }
    assert models.AgendaSettingsOut.model_validate(view).model_dump() == view


def test_settings_out_without_bot_token(monkeypatch):
    monkeypatch.setenv("DISCORD_AGENDA_CHANNEL_ID", CHANNEL_ID)
    h.fake_discord.add_channel(CHANNEL_ID)
    monkeypatch.setattr(config, "DISCORD_BOT_TOKEN", "")
    view = h.run(agenda_settings.settings_out(h.run(agenda_settings.get_settings()), is_responsable=True))
    assert view["channel_status"] == "inaccessible"
    assert view["configured"] is False
    assert view["enabled"] is True


# ---------------------------------------------------------------------------
# Modèles (validation de structure)
# ---------------------------------------------------------------------------

def _invalid(model, data) -> list[str]:
    with pytest.raises(ValidationError) as excinfo:
        model.model_validate(data)
    return [error["type"] for error in excinfo.value.errors()]


def test_legacy_absence_entry_compatible():
    entry = models.AbsenceEntry(id="absence-1", helper={"id": "1", "username": "u"}, start_date="2026-10-01",
                                end_date="2026-10-03", created_at="2026-09-30T10:00:00+00:00")
    assert entry.open_ended is False
    assert entry.model_dump()["open_ended"] is False
    legacy = models.AbsenceEntry(id="absence-2", helper={"id": "1", "username": "u"}, start_date="2026-10-01",
                                 end_date="9999-12-31", open_ended=True, created_at="2026-09-30T10:00:00+00:00")
    assert legacy.end_date == models.OPEN_END_SENTINEL == "9999-12-31"
    # Les anciens modèles de création restent inchangés (end_date obligatoire, 50 000 caractères).
    assert "missing" in _invalid(models.AbsenceCreate, {"start_date": "2026-10-01"})
    assert "string_too_long" in _invalid(
        models.MeetingSummaryUpdate, {"title": "t", "content_markdown": "x" * 50001}
    )


def test_inputs_forbid_unknown_fields():
    assert "extra_forbidden" in _invalid(models.AbsenceIn, {"start_date": "2026-10-28", "reminders": {}})
    assert "extra_forbidden" in _invalid(models.AbsencePatch, {"helper_id": "400000000000000002"})
    assert "extra_forbidden" in _invalid(models.MeetingPatch, {"expected_revision": 0, "agenda": "x"})
    assert "extra_forbidden" in _invalid(models.ReminderConfig, {"enabled": True, "ping": True})
    assert "extra_forbidden" in _invalid(models.AgendaSettingsIn, {"channel": CHANNEL_ID})


def test_typed_fields_are_strict():
    assert "string_pattern_mismatch" in _invalid(models.AbsenceIn, {"start_date": "28/10/2026"})
    assert "value_error" in _invalid(models.AbsenceIn, {"start_date": "2026-02-30"})
    assert "string_pattern_mismatch" in _invalid(
        models.AbsenceIn, {"start_date": "2026-10-28", "helper_id": "٤٠٠٠٠٠٠٠٠٠٠٠٠٠٠٠٠٢"}
    )
    base = {"type": "evenement", "title": "Soirée", "start_date": "2026-10-29"}
    assert "string_pattern_mismatch" in _invalid(models.EntryIn, {**base, "start_time": "24:00"})
    assert "literal_error" in _invalid(models.EntryIn, {**base, "type": "absence"})
    assert "string_too_short" in _invalid(models.EntryIn, {**base, "title": "   "})
    assert "too_long" in _invalid(
        models.EntryIn, {**base, "participant_ids": [str(400000000000000000 + i) for i in range(51)]}
    )
    assert "string_pattern_mismatch" in _invalid(
        models.MeetingPatch, {"expected_revision": 0, "agenda_items": [{"id": "a.b", "title": "x"}]}
    )
    assert "string_pattern_mismatch" in _invalid(
        models.MeetingPatch, {"expected_revision": 0, "attendance": {"x": "present"}}
    )
    assert "literal_error" in _invalid(
        models.MeetingPatch, {"expected_revision": 0, "attendance": {"400000000000000003": "peut-etre"}}
    )
    assert "string_too_long" in _invalid(
        models.MeetingPatch, {"expected_revision": 0, "content_markdown": "x" * (models.MEETING_CONTENT_MAX + 1)}
    )
    assert "missing" in _invalid(models.MeetingPatch, {"title": "x"})
    assert "greater_than_equal" in _invalid(models.MeetingPatch, {"expected_revision": -1})


def test_entry_defaults_and_trimming():
    entry = models.EntryIn.model_validate({
        "type": "autre", "title": "  Formation  ", "custom_label": "  Atelier ", "start_date": "2026-10-29",
        "description": None, "location": None, "participant_ids": ["400000000000000005", "400000000000000005"],
    })
    assert entry.title == "Formation"
    assert entry.custom_label == "Atelier"
    assert (entry.description, entry.location) == ("", "")
    assert entry.all_day is True
    assert entry.participant_ids == ["400000000000000005"]
    assert entry.reminders.model_dump() == {
        "enabled": True, "offsets": ["J-7", "J-2", "J-1", "H-1"], "ping_role": False,
    }


def test_reminder_config_normalized():
    config_in = models.ReminderConfig.model_validate({"offsets": ["H-1", "J-1", "H-1", "J-7"]})
    assert config_in.offsets == ["J-7", "J-1", "H-1"]
    assert config_in.enabled is True
    assert models.ReminderConfig.model_validate({"enabled": True, "offsets": []}).enabled is False
    assert "literal_error" in _invalid(models.ReminderConfig, {"offsets": ["J-3"]})
    # Les trois champs comptent comme envoyés : un PATCH qui envoie {"enabled": true} garde les paliers par défaut.
    patch = models.EntryPatch.model_validate({"reminders": {"enabled": True}})
    assert patch.model_dump(exclude_unset=True) == {
        "reminders": {"enabled": True, "offsets": ["J-7", "J-2", "J-1", "H-1"], "ping_role": False}
    }
    # …mais sent_fields garde les champs réellement envoyés (ping_role absent : la mention stockée est conservée).
    assert patch.reminders.sent_fields == frozenset({"enabled"})
    assert "ping_role" not in patch.reminders.sent_fields
    assert models.ReminderConfig.model_validate({"ping_role": True}).sent_fields == frozenset({"ping_role"})
    assert models.ReminderConfig().sent_fields == frozenset()
    assert models.normalize_offsets(["H-1", "inconnu", "J-2"]) == ["J-2", "H-1"]


def test_patch_models_distinguish_absent_and_null():
    patch = models.EntryPatch.model_validate({"end_date": None, "start_time": None, "description": None})
    assert patch.model_dump(exclude_unset=True) == {"end_date": None, "start_time": None, "description": ""}
    assert models.null_required_message(patch.model_dump(exclude_unset=True)) is None

    labels = {
        (models.EntryPatch, "title"): "titre",
        (models.EntryPatch, "type"): "type",
        (models.EntryPatch, "start_date"): "date de début",
        (models.EntryPatch, "all_day"): "toute la journée",
        (models.EntryPatch, "reminders"): "rappels",
        (models.AbsencePatch, "open_ended"): "fin indéterminée",
        (models.AbsencePatch, "start_date"): "date de début",
    }
    for (model, field_name), label in labels.items():
        fields = model.model_validate({field_name: None}).model_dump(exclude_unset=True)
        assert models.null_required_message(fields) == f"Champ obligatoire : {label}."

    meeting_labels = {"meeting_date": "date", "cancelled": "annulation", "title": "titre", "reminders": "rappels"}
    for field_name, label in meeting_labels.items():
        patch = models.MeetingPatch.model_validate({"expected_revision": 2, field_name: None})
        fields = patch.model_dump(exclude_unset=True)
        assert models.null_required_message(fields) == f"Champ obligatoire : {label}."
    fields = models.MeetingPatch.model_validate({"expected_revision": None}).model_dump(exclude_unset=True)
    assert models.null_required_message(fields) == "Champ obligatoire : révision."

    meeting = models.MeetingPatch.model_validate({
        "expected_revision": 3, "location": None, "cancel_reason": None, "content_markdown": None,
        "participant_ids": None, "attendance": None, "start_time": None, "end_time": None,
    })
    assert meeting.model_dump(exclude_unset=True) == {
        "expected_revision": 3, "location": "", "cancel_reason": "", "content_markdown": "",
        "participant_ids": [], "attendance": {}, "start_time": None, "end_time": None,
    }
    assert models.AbsencePatch.model_validate({"reason": None}).model_dump(exclude_unset=True) == {"reason": ""}


def test_action_items_keep_per_element_presence():
    patch = models.MeetingPatch.model_validate({
        "expected_revision": 1,
        "action_items": [
            {"id": "x1", "text": " Mettre à jour le planning "},
            {"id": "x2", "text": "Relancer", "assignee_id": None, "done": True, "due_date": None},
            {"text": "Nouvelle action"},
        ],
    })
    first, second, third = patch.action_items
    assert first.text == "Mettre à jour le planning"
    assert first.model_fields_set == {"id", "text"}  # done, assignee_id, due_date absents : valeurs stockées gardées
    assert second.model_fields_set == {"id", "text", "assignee_id", "done", "due_date"}
    assert (second.assignee_id, second.done) == (None, True)
    assert third.id is None and third.done is None
    assert "string_too_short" in _invalid(models.ActionItemIn, {"text": "  "})
    assert "missing" in _invalid(models.ActionItemIn, {"id": "x1"})


def test_meeting_create_and_misc_inputs():
    meeting = models.MeetingCreateIn.model_validate({
        "title": "Réunion mensuelle de novembre", "meeting_date": "2026-10-30", "start_time": "20:30",
        "agenda_items": [{"title": "Tour de table"}, {"id": "a2", "title": " Planning ", "done": True}],
        "reminders": {"enabled": True, "offsets": ["J-7", "J-2", "J-1", "H-1"], "ping_role": True},
    })
    assert [item.title for item in meeting.agenda_items] == ["Tour de table", "Planning"]
    assert meeting.agenda_items[0].id is None and meeting.agenda_items[0].done is False
    assert meeting.location == "" and meeting.participant_ids == []
    assert models.AbsenceReturn.model_validate({}).return_date is None
    assert models.SettingsTestIn.model_validate({}).ping is False
    assert "missing" in _invalid(models.ActionToggle, {})
    assert "missing" in _invalid(models.MeetingLockIn, {})
    absence = models.AbsenceIn.model_validate({"start_date": "2026-10-28", "open_ended": True, "reason": "  Vacances "})
    assert (absence.end_date, absence.open_ended, absence.reason, absence.helper_id) == (None, True, "Vacances", None)


def test_output_models_accept_spec_examples():
    identity = {"id": "400000000000000004", "username": "responsable", "display_name": "Lou (responsable)",
                "avatar_url": None}
    schedule = [{"offset": "J-7", "due_at": "2026-10-22T18:30:00Z", "status": "skipped",
                 "skip_reason": "past_at_creation", "sent_at": None},
                {"offset": "H-1", "due_at": None, "status": "skipped", "skip_reason": "no_time", "sent_at": None}]
    entry = models.EntryOut.model_validate({
        "id": "e1", "type": "evenement", "title": "Soirée", "all_day": False, "start_date": "2026-10-29",
        "start_time": "20:30", "end_time": "22:30", "participants": [identity],
        "reminders": {"enabled": True, "offsets": ["J-7", "H-1"], "ping_role": True, "schedule": schedule},
        "created_by": identity, "created_at": "2026-10-25T18:00:00+00:00", "can_edit": True, "_id": "ignoré",
    })
    assert entry.reminders.schedule[1].due_at is None
    absence = models.AbsenceOut.model_validate({
        "id": "a1", "helper": identity, "start_date": "2026-10-22", "end_date": None, "open_ended": True,
        "reason": "Indisponible", "phase": "en_cours", "created_at": "2026-10-22T08:12:00+00:00",
        "created_by": identity, "updated_at": None, "can_edit": True,
    })
    summary = {
        "id": "m1", "title": "Point modération", "meeting_date": "2026-10-22", "start_time": "21:00",
        "phase": "redige", "status": "redige", "author": identity, "participants_count": 1,
        "participant_ids": ["400000000000000003"], "is_participant": True, "agenda_preview": ["Tour de table"],
        "agenda_count": 1, "word_count": 412, "excerpt": "Bilan…", "updated_at": "2026-10-23T09:10:00+00:00",
        "can_manage": True,
    }
    detail = models.MeetingDetailOut.model_validate({
        **summary, "agenda": "1. Tour de table", "agenda_items": [{"id": "a1", "title": "Tour de table", "done": True}],
        "content_format": "blocknote", "decisions": [{"id": "d1", "text": "OK"}],
        "action_items": [{"id": "x1", "text": "Planning", "assignee": identity, "due_date": "2026-10-30"}],
        "participants": [{**identity, "attendance": "present"}], "participants_absent": [],
        "reminders": {"enabled": False, "offsets": [], "ping_role": False, "schedule": []}, "revision": 7,
        "viewer": {"id": "400000000000000077", "is_responsable": True},
    })
    assert detail.participants[0].attendance == "present"
    feed = models.FeedOut.model_validate({
        "today": "2026-10-25", "range": {"start": "2026-09-28", "end": "2026-11-08"},
        "viewer": {"id": "1", "is_responsable": False}, "absences": [absence.model_dump()],
        "meetings": [summary], "entries": [entry.model_dump()],
    })
    assert feed.timezone == "Europe/Paris"
    upcoming = models.UpcomingOut.model_validate({
        "today": "2026-10-25", "viewer": {"id": "1", "is_responsable": False},
        "next_events": [{"kind": "meeting", "id": "m1", "type": "reunion", "title": "Réunion",
                         "start_date": "2026-10-30", "start_time": "20:30", "all_day": False,
                         "location": "Vocal Staff", "cancelled": False}],
    })
    assert upcoming.next_events[0].end_date is None
    overview = models.MeetingOverviewOut.model_validate({
        "today": "2026-10-25", "viewer": {"id": "1", "is_responsable": False}, "next_meeting": detail.model_dump(),
        "to_write": [summary],
        "open_actions": [{"meeting_id": "m1", "meeting_title": "Point", "meeting_date": "2026-10-17",
                          "is_mine": True, "item": {"id": "x1", "text": "Planning"}}],
        "counts": {"a_venir": 2, "a_rediger": 1, "open_actions": 4, "my_open_actions": 1},
    })
    assert overview.open_actions[0].item.done is False
    listing = models.MeetingListOut.model_validate({
        "items": [summary], "total": 1, "limit": 50, "offset": 0,
        "counts": {"all": 1, "a_venir": 0, "a_rediger": 0, "redige": 1, "annulee": 0},
        "viewer": {"id": "1", "is_responsable": False},
    })
    assert listing.counts.all == 1
    conflict = models.RevisionConflictOut(
        current_revision=8, updated_at="2026-10-25T19:02:11+00:00", updated_by=identity
    )
    assert conflict.model_dump()["code"] == "revision_conflict"
    assert conflict.detail == "Ce compte-rendu a été modifié par quelqu'un d'autre. Rechargez avant de continuer."
    saved = models.MeetingSaveResult.model_validate({
        "id": "m1", "revision": 8, "updated_at": None, "updated_by": identity,
        "status": "redige", "phase": "redige", "word_count": 418,
    })
    assert saved.revision == 8
    toggle = models.ActionToggleOut.model_validate({"meeting_id": "m1", "revision": 8,
                                                    "item": {"id": "x1", "text": "t", "done": True,
                                                             "done_at": "2026-10-25T19:05:00Z", "done_by": identity}})
    assert toggle.item.done_by.id == identity["id"]
    test_out = models.SettingsTestOut.model_validate(
        {"ok": True, "message_id": "600000000000000001", "channel_id": CHANNEL_ID}
    )
    assert test_out.ok is True
