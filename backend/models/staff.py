from datetime import date
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    StringConstraints,
    field_validator,
    model_validator,
)

from models.ticket import HelperIdentity


class AbsenceEntry(BaseModel):
    id: str
    helper: HelperIdentity
    start_date: str
    # Vue legacy : une absence sans fin y porte la sentinelle "9999-12-31".
    end_date: str
    open_ended: bool = False
    reason: str = ""
    created_at: str


class AbsenceCreate(BaseModel):
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str = Field(default="", max_length=500)


class QuarterlyPeriodCreate(BaseModel):
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class QuarterlyPeriod(BaseModel):
    id: str
    start_date: str
    end_date: str
    is_archived: bool = False
    created_by: dict
    created_at: str


class QuarterlyTaskCreate(BaseModel):
    period_id: str
    name: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=80)
    explanation: str = Field(default="", max_length=2000)
    task_date: str = Field(min_length=1, max_length=120)
    end_date: str | None = Field(default=None, max_length=120)
    target_role: Literal["staff", "helper", "tous"] = "tous"


class QuarterlyTask(BaseModel):
    id: str
    period_id: str
    name: str
    category: str
    explanation: str
    task_date: str
    end_date: str | None = None
    target_role: Literal["staff", "helper", "tous"] = "tous"
    created_by: dict
    volunteers: list[dict] = []
    created_at: str
    updated_at: str


class VolunteerRating(BaseModel):
    rating: int = Field(ge=1, le=5)
    note: str = Field(default="", max_length=500)


MeetingStatus = Literal["en_attente_resume", "redige"]


class MeetingSummary(BaseModel):
    id: str
    title: str
    agenda: str = ""
    content_markdown: str = ""
    status: MeetingStatus = "en_attente_resume"
    meeting_date: str
    author: HelperIdentity
    created_at: str
    updated_at: str
    is_locked: bool = False


class MeetingSummaryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    agenda: str = Field(default="", max_length=4000)
    content_markdown: str = Field(default="", max_length=50000)
    meeting_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class MeetingSummaryUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    agenda: str = Field(default="", max_length=4000)
    content_markdown: str = Field(default="", max_length=50000)


# ---------------------------------------------------------------------------
# Agenda (/api/agenda/*) : types communs
# ---------------------------------------------------------------------------

# [0-9] et non \d : le moteur de motifs de Pydantic accepte sinon les chiffres non ASCII.
DATE_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
TIME_PATTERN = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"
DISCORD_ID_PATTERN = r"^[0-9]{17,20}$"
CLIENT_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"

REMINDER_OFFSETS: tuple[str, ...] = ("J-7", "J-2", "J-1", "H-1")
ENTRY_TYPES: tuple[str, ...] = ("evenement", "echeance", "rappel", "permanence", "autre")
ENTRY_TYPE_LABELS = {
    "absence": "Absence",
    "reunion": "Réunion",
    "evenement": "Événement",
    "echeance": "Échéance",
    "rappel": "Rappel",
    "permanence": "Permanence",
    "autre": "Autre",
}
MEETING_CONTENT_MAX = 400_000
# Fin d'une absence sans fin, uniquement en sortie de l'ancien GET /api/staff/calendrier (jamais en base).
OPEN_END_SENTINEL = "9999-12-31"

# Libellés du 422 « Champ obligatoire : <libellé>. » quand un PATCH envoie null sur un champ requis.
REQUIRED_FIELD_LABELS = {
    "expected_revision": "révision",
    "title": "titre",
    "type": "type",
    "start_date": "date de début",
    "meeting_date": "date",
    "all_day": "toute la journée",
    "open_ended": "fin indéterminée",
    "cancelled": "annulation",
    "reminders": "rappels",
}


def null_required_message(fields: dict) -> str | None:
    """Message du 422 si un champ obligatoire est envoyé à null (fields = model_dump(exclude_unset=True))."""
    for name, label in REQUIRED_FIELD_LABELS.items():
        if name in fields and fields[name] is None:
            return f"Champ obligatoire : {label}."
    return None


def normalize_offsets(offsets) -> list[str]:
    """Paliers sans doublon, dans l'ordre J-7, J-2, J-1, H-1 (valeurs inconnues ignorées)."""
    wanted = set(offsets or [])
    return [offset for offset in REMINDER_OFFSETS if offset in wanted]


def _real_date(value: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Date inexistante.") from exc
    return value


def _unique(values: list) -> list:
    return list(dict.fromkeys(values))


DateStr = Annotated[str, StringConstraints(pattern=DATE_PATTERN), AfterValidator(_real_date)]
TimeStr = Annotated[str, StringConstraints(pattern=TIME_PATTERN)]
DiscordId = Annotated[str, StringConstraints(pattern=DISCORD_ID_PATTERN)]
ClientId = Annotated[str, StringConstraints(pattern=CLIENT_ID_PATTERN)]

ReminderOffset = Literal["J-7", "J-2", "J-1", "H-1"]
EntryType = Literal["evenement", "echeance", "rappel", "permanence", "autre"]
AgendaItemType = Literal["reunion", "evenement", "echeance", "rappel", "permanence", "autre"]
Attendance = Literal["invite", "present", "absent", "excuse"]
MeetingPhase = Literal["a_venir", "a_rediger", "redige", "annulee"]
AbsencePhase = Literal["a_venir", "en_cours", "passee"]
ReminderStatus = Literal["pending", "sending", "sent", "skipped", "failed", "cancelled"]
ContentFormat = Literal["empty", "blocknote", "text"]
ChannelStatus = Literal["ok", "inaccessible", "non_configure"]
ChannelVisibility = Literal["staff", "public", "inconnu"]
SettingsSource = Literal["env", "db"]

ParticipantIds = Annotated[list[DiscordId], Field(max_length=50), AfterValidator(_unique)]
Title160 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Title200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text40 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)]
Text200 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Text300 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
Text500 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Text2000 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
ActionText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
DecisionText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
MeetingContent = Annotated[str, StringConstraints(max_length=MEETING_CONTENT_MAX)]


class AgendaInput(BaseModel):
    """Base des corps de requête de l'agenda : tout champ inconnu est refusé (422)."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Agenda : entrées
# ---------------------------------------------------------------------------

class ReminderConfig(AgendaInput):
    enabled: bool = True
    offsets: list[ReminderOffset] = Field(default_factory=lambda: list(REMINDER_OFFSETS), max_length=8)
    ping_role: bool = False

    _sent: frozenset[str] = PrivateAttr(default_factory=frozenset)

    @model_validator(mode="after")
    def _normalize(self):
        self._sent = frozenset(self.model_fields_set)
        # Les trois champs sont réaffectés : ils comptent ainsi comme envoyés (model_dump(exclude_unset=True)).
        self.offsets = normalize_offsets(self.offsets)
        self.enabled = bool(self.enabled and self.offsets)
        self.ping_role = bool(self.ping_role)
        return self

    @property
    def sent_fields(self) -> frozenset[str]:
        """Champs réellement présents dans la requête (model_fields_set les compte tous après normalisation)."""
        return self._sent


class AbsenceIn(AgendaInput):
    start_date: DateStr
    end_date: DateStr | None = None
    open_ended: bool = False
    reason: Text500 = ""
    helper_id: DiscordId | None = None

    @field_validator("reason", mode="before")
    @classmethod
    def _null_reason(cls, value):
        return "" if value is None else value


class AbsencePatch(AgendaInput):
    start_date: DateStr | None = None
    end_date: DateStr | None = None
    open_ended: bool | None = None
    reason: Text500 | None = None

    @field_validator("reason", mode="before")
    @classmethod
    def _null_reason(cls, value):
        return "" if value is None else value


class AbsenceReturn(AgendaInput):
    return_date: DateStr | None = None


RecurrenceFreq = Literal["weekly", "biweekly", "monthly"]


class RecurrenceIn(AgendaInput):
    """Récurrence d'une entrée : chaque semaine, toutes les 2 semaines ou chaque mois, jusqu'à `until` inclus."""

    freq: RecurrenceFreq
    until: DateStr


class RecurrenceOut(BaseModel):
    freq: RecurrenceFreq
    until: str


class EntryIn(AgendaInput):
    type: EntryType
    title: Title160
    custom_label: Text40 | None = None
    description: Text2000 = ""
    all_day: bool = True
    start_date: DateStr
    end_date: DateStr | None = None
    start_time: TimeStr | None = None
    end_time: TimeStr | None = None
    location: Text200 = ""
    participant_ids: ParticipantIds = Field(default_factory=list)
    reminders: ReminderConfig = Field(default_factory=ReminderConfig)
    recurrence: RecurrenceIn | None = None

    @field_validator("description", "location", mode="before")
    @classmethod
    def _null_text(cls, value):
        return "" if value is None else value

    @field_validator("participant_ids", mode="before")
    @classmethod
    def _null_list(cls, value):
        return [] if value is None else value


class EntryPatch(AgendaInput):
    type: EntryType | None = None
    title: Title160 | None = None
    custom_label: Text40 | None = None
    description: Text2000 | None = None
    all_day: bool | None = None
    start_date: DateStr | None = None
    end_date: DateStr | None = None
    start_time: TimeStr | None = None
    end_time: TimeStr | None = None
    location: Text200 | None = None
    participant_ids: ParticipantIds | None = None
    reminders: ReminderConfig | None = None
    recurrence: RecurrenceIn | None = None

    @field_validator("description", "location", mode="before")
    @classmethod
    def _null_text(cls, value):
        return "" if value is None else value

    @field_validator("participant_ids", mode="before")
    @classmethod
    def _null_list(cls, value):
        return [] if value is None else value


class AgendaItemIn(AgendaInput):
    id: ClientId | None = None
    title: Title200
    done: bool = False


class DecisionIn(AgendaInput):
    id: ClientId | None = None
    text: DecisionText


class ActionItemIn(AgendaInput):
    """Élément de action_items (PATCH) : un champ absent garde la valeur stockée (model_fields_set)."""

    id: ClientId | None = None
    text: ActionText
    assignee_id: DiscordId | None = None
    due_date: DateStr | None = None
    done: bool | None = None


class MeetingCreateIn(AgendaInput):
    title: Title160
    meeting_date: DateStr
    start_time: TimeStr | None = None
    end_time: TimeStr | None = None
    location: Text200 = ""
    participant_ids: ParticipantIds = Field(default_factory=list)
    agenda_items: list[AgendaItemIn] = Field(default_factory=list, max_length=50)
    reminders: ReminderConfig = Field(default_factory=ReminderConfig)

    @field_validator("location", mode="before")
    @classmethod
    def _null_text(cls, value):
        return "" if value is None else value

    @field_validator("participant_ids", "agenda_items", mode="before")
    @classmethod
    def _null_list(cls, value):
        return [] if value is None else value


class MeetingPatch(AgendaInput):
    # Obligatoire (absent : 422 Pydantic) ; null : 422 « Champ obligatoire : révision. » dans le service.
    expected_revision: Annotated[int, Field(ge=0)] | None
    title: Title160 | None = None
    content_markdown: MeetingContent | None = None
    agenda_items: list[AgendaItemIn] | None = Field(default=None, max_length=50)
    decisions: list[DecisionIn] | None = Field(default=None, max_length=50)
    action_items: list[ActionItemIn] | None = Field(default=None, max_length=50)
    attendance: dict[DiscordId, Attendance] | None = Field(default=None, max_length=50)
    meeting_date: DateStr | None = None
    start_time: TimeStr | None = None
    end_time: TimeStr | None = None
    location: Text200 | None = None
    participant_ids: ParticipantIds | None = None
    reminders: ReminderConfig | None = None
    cancelled: bool | None = None
    cancel_reason: Text300 | None = None

    @field_validator("content_markdown", "location", "cancel_reason", mode="before")
    @classmethod
    def _null_text(cls, value):
        return "" if value is None else value

    @field_validator("agenda_items", "decisions", "action_items", "participant_ids", mode="before")
    @classmethod
    def _null_list(cls, value):
        return [] if value is None else value

    @field_validator("attendance", mode="before")
    @classmethod
    def _null_dict(cls, value):
        return {} if value is None else value


class ActionToggle(AgendaInput):
    done: bool


class MeetingLockIn(AgendaInput):
    locked: bool


class AgendaSettingsIn(AgendaInput):
    """PUT des réglages : un champ absent est inchangé. null sur channel_id / ping_role_id les efface ;
    null sur enabled / day_reminder_time revient à la valeur de l'environnement."""

    enabled: bool | None = None
    channel_id: DiscordId | None = None
    ping_role_id: DiscordId | None = None
    day_reminder_time: TimeStr | None = None


class SettingsTestIn(AgendaInput):
    ping: bool = False


# ---------------------------------------------------------------------------
# Agenda : sorties
# ---------------------------------------------------------------------------

class ReminderScheduleItem(BaseModel):
    offset: ReminderOffset
    due_at: str | None = None
    status: ReminderStatus
    skip_reason: str | None = None
    sent_at: str | None = None


class ReminderInfo(BaseModel):
    enabled: bool = False
    offsets: list[ReminderOffset] = Field(default_factory=list)
    ping_role: bool = False
    schedule: list[ReminderScheduleItem] = Field(default_factory=list)


class Viewer(BaseModel):
    id: str
    is_responsable: bool = False


class AbsenceOut(BaseModel):
    id: str
    helper: HelperIdentity
    start_date: str
    end_date: str | None = None
    open_ended: bool = False
    reason: str = ""
    phase: AbsencePhase
    created_at: str | None = None
    created_by: HelperIdentity | None = None
    updated_at: str | None = None
    updated_by: HelperIdentity | None = None
    can_edit: bool = False


class EntryOut(BaseModel):
    id: str
    type: EntryType
    custom_label: str | None = None
    title: str
    description: str = ""
    all_day: bool = True
    start_date: str
    end_date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    location: str = ""
    participants: list[HelperIdentity] = Field(default_factory=list)
    reminders: ReminderInfo = Field(default_factory=ReminderInfo)
    created_by: HelperIdentity | None = None
    created_at: str | None = None
    updated_by: HelperIdentity | None = None
    updated_at: str | None = None
    can_edit: bool = False
    # Récurrence : `series_start_date` = début de la série (la date de l'occurrence est `start_date`).
    recurrence: RecurrenceOut | None = None
    series_start_date: str | None = None


class AgendaItemOut(BaseModel):
    id: str
    title: str
    done: bool = False


class DecisionOut(BaseModel):
    id: str
    text: str


class ActionItemOut(BaseModel):
    id: str
    text: str
    assignee: HelperIdentity | None = None
    due_date: str | None = None
    done: bool = False
    done_at: str | None = None
    done_by: HelperIdentity | None = None


class ParticipantOut(HelperIdentity):
    attendance: Attendance = "invite"


class MeetingSummaryOut(BaseModel):
    id: str
    title: str
    meeting_date: str
    start_time: str | None = None
    end_time: str | None = None
    location: str = ""
    phase: MeetingPhase
    status: MeetingStatus = "en_attente_resume"
    is_locked: bool = False
    cancelled: bool = False
    author: HelperIdentity | None = None
    participants_count: int = 0
    participant_ids: list[str] = Field(default_factory=list)
    is_participant: bool = False
    agenda_preview: list[str] = Field(default_factory=list)
    agenda_count: int = 0
    agenda_done_count: int = 0
    decisions_count: int = 0
    actions_count: int = 0
    open_actions_count: int = 0
    word_count: int = 0
    excerpt: str = ""
    updated_at: str | None = None
    can_manage: bool = False


class MeetingDetailOut(MeetingSummaryOut):
    agenda: str = ""
    agenda_items: list[AgendaItemOut] = Field(default_factory=list)
    content_markdown: str = ""
    content_format: ContentFormat = "empty"
    decisions: list[DecisionOut] = Field(default_factory=list)
    action_items: list[ActionItemOut] = Field(default_factory=list)
    participants: list[ParticipantOut] = Field(default_factory=list)
    participants_absent: list[str] = Field(default_factory=list)
    reminders: ReminderInfo = Field(default_factory=ReminderInfo)
    revision: int = 0
    created_at: str | None = None
    updated_by: HelperIdentity | None = None
    locked_by: HelperIdentity | None = None
    locked_at: str | None = None
    cancel_reason: str = ""
    can_edit: bool = False
    viewer: Viewer


class MeetingSaveResult(BaseModel):
    id: str
    revision: int
    updated_at: str | None = None
    updated_by: HelperIdentity | None = None
    status: MeetingStatus
    phase: MeetingPhase
    word_count: int = 0


class RevisionConflictOut(BaseModel):
    """Corps du 409 (renvoyé en JSONResponse, pas en HTTPException)."""

    detail: str = "Ce compte-rendu a été modifié par quelqu'un d'autre. Rechargez avant de continuer."
    code: Literal["revision_conflict"] = "revision_conflict"
    current_revision: int
    updated_at: str | None = None
    updated_by: HelperIdentity | None = None


class ActionToggleOut(BaseModel):
    meeting_id: str
    revision: int
    item: ActionItemOut


class MeetingPhaseCounts(BaseModel):
    all: int = 0
    a_venir: int = 0
    a_rediger: int = 0
    redige: int = 0
    annulee: int = 0


class MeetingListOut(BaseModel):
    items: list[MeetingSummaryOut] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0
    counts: MeetingPhaseCounts = Field(default_factory=MeetingPhaseCounts)
    viewer: Viewer


class OpenActionRef(BaseModel):
    meeting_id: str
    meeting_title: str
    meeting_date: str
    is_mine: bool = False
    item: ActionItemOut


class OverviewCounts(BaseModel):
    a_venir: int = 0
    a_rediger: int = 0
    open_actions: int = 0
    my_open_actions: int = 0


class MeetingOverviewOut(BaseModel):
    today: str
    viewer: Viewer
    next_meeting: MeetingDetailOut | None = None
    to_write: list[MeetingSummaryOut] = Field(default_factory=list)
    open_actions: list[OpenActionRef] = Field(default_factory=list)
    counts: OverviewCounts = Field(default_factory=OverviewCounts)


class DateRange(BaseModel):
    start: str
    end: str


class FeedOut(BaseModel):
    today: str
    timezone: str = "Europe/Paris"
    range: DateRange
    viewer: Viewer
    absences: list[AbsenceOut] = Field(default_factory=list)
    meetings: list[MeetingSummaryOut] = Field(default_factory=list)
    entries: list[EntryOut] = Field(default_factory=list)


class NextEventRef(BaseModel):
    kind: Literal["meeting", "entry"]
    id: str
    type: AgendaItemType
    custom_label: str | None = None
    title: str
    start_date: str
    end_date: str | None = None
    start_time: str | None = None
    all_day: bool = False
    location: str = ""
    cancelled: bool = False


class UpcomingOut(BaseModel):
    today: str
    viewer: Viewer
    absences_current: list[AbsenceOut] = Field(default_factory=list)
    absences_upcoming: list[AbsenceOut] = Field(default_factory=list)
    next_events: list[NextEventRef] = Field(default_factory=list)


class AgendaSettingsOut(BaseModel):
    enabled: bool
    disabled_by_env: bool = False
    configured: bool = False
    channel_status: ChannelStatus = "non_configure"
    channel_name: str | None = None
    channel_visibility: ChannelVisibility = "inconnu"
    channel_id: str | None = None
    ping_role_id: str | None = None
    ping_role_configured: bool = False
    day_reminder_time: str = "10:00"
    default_offsets: list[ReminderOffset] = Field(default_factory=lambda: list(REMINDER_OFFSETS))
    timezone: str = "Europe/Paris"
    source: SettingsSource = "env"


class SettingsTestOut(BaseModel):
    ok: bool = True
    message_id: str | None = None
    channel_id: str
