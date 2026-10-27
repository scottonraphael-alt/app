"""Modeles Pydantic pour la gestion des projets."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ProjectMemberAdd(BaseModel):
    member_id: str = Field(pattern=r"\d{15,22}")
    role: Literal["membre", "responsable"] = "membre"


class ProjectMember(BaseModel):
    id: str
    username: str
    display_name: str
    avatar_url: str | None = None
    role: Literal["responsable", "membre"] = "membre"


class ChecklistItem(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    done: bool = False

    @field_validator("title")
    @classmethod
    def non_blank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Le titre de l'étape est requis.")
        return value


class ProjectReview(BaseModel):
    attendance: int | None = Field(default=None, ge=0, le=1000000)
    event_date: date | None = None
    successes: str = Field(default="", max_length=4000)
    improvements: str = Field(default="", max_length=4000)
    next_steps: str = Field(default="", max_length=4000)
    updated_at: str
    updated_by: ProjectMember


class RundownStepInput(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    duration_minutes: int = Field(ge=1, le=2147483647, strict=True)
    speaker_id: str | None = Field(default=None, max_length=80)
    notes: str = Field(default="", max_length=1500)

    @field_validator("title")
    @classmethod
    def non_blank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Le titre de la séquence est requis.")
        return value


class RundownStep(BaseModel):
    id: str
    title: str
    duration_minutes: int
    speaker: ProjectMember | None = None
    notes: str = ""


class ProjectRundown(BaseModel):
    event_date: date | None = None
    start_time: str = "20:00"
    items: list[RundownStep] = Field(default_factory=list)
    updated_at: str
    updated_by: ProjectMember


class ProjectCreate(BaseModel):
    template_id: str | None = Field(default=None, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    priority: Literal["basse", "normale", "haute"] = "normale"
    tags: list[str] = Field(default_factory=list, max_length=8)
    start_date: date
    end_date: date | None = None

    @field_validator("end_date")
    @classmethod
    def check_end_date(cls, end_date, info):
        start_date = info.data.get("start_date")
        if end_date and start_date and end_date < start_date:
            raise ValueError("end_date doit etre posterieure ou egale a start_date")
        return end_date


class ProjectUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = ""
    content_markdown: str = ""
    end_date: date | None = None
    status: Literal["en_cours", "termine", "archive"] | None = None


class Project(BaseModel):
    id: str
    title: str
    description: str
    content_markdown: str = ""
    status: Literal["en_cours", "termine", "archive"] = "en_cours"
    priority: Literal["basse", "normale", "haute"] = "normale"
    tags: list[str] = Field(default_factory=list)
    start_date: date
    end_date: date | None = None
    members: list[ProjectMember] = Field(default_factory=list)
    created_by: ProjectMember
    template_id: str | None = None
    review: ProjectReview | None = None
    rundown: ProjectRundown | None = None
    created_at: datetime
    updated_at: datetime


class ProjectTaskCreate(BaseModel):
    checklist: list[ChecklistItem] = Field(default_factory=list, max_length=50)
    project_id: str | None = None
    assignee_id: str
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    priority: Literal["basse", "normale", "haute"] = "normale"
    due_date: date


class ProjectSubmissionFile(BaseModel):
    original_filename: str
    content_type: str | None = None
    size: int = 0
    storage_path: str | None = None


class ProjectTask(BaseModel):
    checklist: list[ChecklistItem] = Field(default_factory=list)
    id: str
    project_id: str
    title: str
    description: str = ""
    due_date: date
    assignee: ProjectMember
    status: Literal["a_faire", "en_cours", "rendu", "valide"] = "a_faire"
    priority: Literal["basse", "normale", "haute"] = "normale"
    blocked_reason: str = ""
    review_note: str = ""
    submission_note: str = ""
    submission_file_url: str | None = None
    submission_file: ProjectSubmissionFile | None = None
    submitted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProjectResource(BaseModel):
    id: str
    project_id: str
    title: str
    original_filename: str
    content_type: str | None = None
    size: int = 0
    storage_path: str
    uploaded_by: ProjectMember
    created_at: datetime
