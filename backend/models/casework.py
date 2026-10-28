"""Contracts for the prepared multi-family ticket workspace."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Kind = Literal['verification', 'summons', 'contact_staff', 'bubble', 'support']


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class ImportChannel(Strict):
    kind: Kind | None = None
    channel_id: str = Field(pattern=r'^[0-9]{17,20}$')


class Change(Strict):
    revision: int = Field(ge=0)
    request_id: str = Field(min_length=8, max_length=80, pattern=r'^[A-Za-z0-9_:\-]+$')
    action: Literal['claim', 'assign', 'note', 'sync', 'archive', 'cancel_close']
    assignee_id: str | None = Field(default=None, pattern=r'^[0-9]{17,20}$')
    text: str = Field(default='', max_length=25000)


class InboxQuery(Strict):
    kind: Kind
    archived: bool = False
