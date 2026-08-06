from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

class DiscordAttachment(BaseModel):
    id: str
    filename: str
    url: str
    content_type: str | None = None
    
class DiscordAuthor(BaseModel):
    id: str
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    is_bot: bool = False


class TranscriptMessage(BaseModel):
    id: str
    content: str
    timestamp: str
    author: DiscordAuthor
    attachments: list[DiscordAttachment] = []
    embeds: list[dict[str, Any]] = []
    components: list[dict[str, Any]] = []
    application_id: str | None = None
    webhook_id: str | None = None
    




class DiscordMember(BaseModel):
    id: str
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    joined_at: str | None = None


class HelperIdentity(BaseModel):
    id: str
    username: str
    display_name: str | None = None
    avatar_url: str | None = None


class AiSummary(BaseModel):
    context: str
    expressed_needs: str
    actions: str
    next_follow_up: str
    generated_at: str
    generated_by: str


class TicketNote(BaseModel):
    id: str
    title: str
    content: str
    author: HelperIdentity
    created_at: str
    updated_at: str


class TicketNoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=25000)


class HelperProfile(BaseModel):
    helper_id: str
    triggers: str = ""
    updated_at: str | None = None


class HelperProfileUpdate(BaseModel):
    triggers: str = Field(max_length=8000)


class TicketCreate(BaseModel):
    member_id: str = Field(pattern=r"^\d{15,22}$")
    channel_id: str = Field(pattern=r"^\d{15,22}$")
    title: str | None = Field(default=None, max_length=120)


class TicketUpdate(BaseModel):
    notes: str | None = Field(default=None, max_length=25000)
    vocal_summary: str | None = Field(default=None, max_length=25000)
    status: Literal["active", "archived"] | None = None
    follow_up_status: Literal["en attente de réponse", "en cours", "à conclure"] | None = None
    person_triggers: str | None = Field(default=None, max_length=8000)


class TicketAssignmentUpdate(BaseModel):
    helper_id: str | None = Field(default=None, pattern=r"^\d{15,22}$")


class TicketSummary(BaseModel):
    id: str
    title: str
    member: DiscordMember
    channel_id: str
    channel_name: str
    status: Literal["active", "archived"]
    message_count: int
    updated_at: str
    created_at: str
    priority: Literal["routine", "prioritaire", "urgent"] = "routine"
    follow_up_status: Literal["en attente de réponse", "en cours", "à conclure"] = "en attente de réponse"
    assigned_helper: HelperIdentity | None = None


class TicketDetail(TicketSummary):
    transcript: list[TranscriptMessage] = Field(default_factory=list)
    notes: str = ""
    vocal_summary: str = ""
    last_synced_at: str | None = None
    created_by: str
    is_demo: bool = False
    ai_summary: AiSummary | None = None
    notes_entries: list[TicketNote] = Field(default_factory=list)
    person_triggers: str = ""


class TicketStats(BaseModel):
    active_count: int
    archived_count: int
    total_messages: int


class AuthenticatedHelper(BaseModel):
    id: str
    username: str
    global_name: str | None = None
    avatar_url: str | None = None
    mode: Literal["discord"] = "discord"


class AuthSession(BaseModel):
    authenticated: bool
    helper: AuthenticatedHelper | None = None
    is_admin: bool = False
    is_staff: bool = False
    is_helper: bool = False
    is_responsable: bool = False
    is_animateur: bool = False
    is_operateur: bool = False


class AdminHelperOverview(BaseModel):
    helper: HelperIdentity
    assigned_count: int
    active_count: int
    tickets: list[TicketSummary] = Field(default_factory=list)
    triggers: str = ""
    profile_updated_at: str | None = None


class AdminOverview(BaseModel):
    total_helpers: int
    active_tickets: int
    unassigned_tickets: int
    helpers: list[AdminHelperOverview] = Field(default_factory=list)
