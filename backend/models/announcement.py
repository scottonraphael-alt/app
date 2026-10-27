"""Bounded authoring schema. Only server-compiled Discord components may be sent."""
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Media(StrictModel):
    url: str = Field(default='', max_length=2048)
    asset_id: str | None = Field(default=None, max_length=80)
    description: str = Field(default='', max_length=1024)
    spoiler: bool = False


class LinkButton(StrictModel):
    label: str = Field(default='', max_length=80)
    url: str = Field(default='', max_length=512)
    emoji: str = Field(default='', max_length=64)
    disabled: bool = False


class Block(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    kind: Literal['text','section','gallery','separator','buttons','file']
    text: str = Field(default='', max_length=4000)
    texts: list[str] = Field(default_factory=list, max_length=3)
    accessory: Literal['thumbnail','button'] = 'thumbnail'
    thumbnail: Media = Field(default_factory=Media)
    button: LinkButton = Field(default_factory=LinkButton)
    items: list[Media] = Field(default_factory=list, max_length=10)
    buttons: list[LinkButton] = Field(default_factory=list, max_length=5)
    divider: bool = True
    spacing: Literal[1,2] = 1
    file_asset_id: str | None = Field(default=None, max_length=80)
    spoiler: bool = False

    @model_validator(mode='after')
    def bounded_section(self):
        if any(len(text)>4000 for text in self.texts):raise ValueError('Texte de section trop long.')
        return self


class Group(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(default='Panneau', max_length=100)
    boxed: bool = True
    color: str | None = Field(default='#78618c', pattern=r'^#[0-9a-fA-F]{6}$')
    spoiler: bool = False
    blocks: list[Block] = Field(default_factory=list, max_length=40)


class Mentions(StrictModel):
    roles: list[str] = Field(default_factory=list, max_length=100)
    users: list[str] = Field(default_factory=list, max_length=100)
    everyone: bool = False


class AnnouncementDocument(StrictModel):
    schema_version: Literal[1] = 1
    groups: list[Group] = Field(min_length=1, max_length=10)
    mentions: Mentions = Field(default_factory=Mentions)
    silent: bool = False

    @model_validator(mode='after')
    def bounded_document(self):
        if len(json.dumps(self.model_dump(),ensure_ascii=False).encode())>150000:raise ValueError('Le brouillon dépasse 150 Ko.')
        ids=[g.id for g in self.groups]+[b.id for g in self.groups for b in g.blocks]
        if len(set(ids))!=len(ids):raise ValueError('Les identifiants des panneaux et blocs doivent être uniques.')
        return self


class DraftSave(StrictModel):
    name: str = Field(min_length=1,max_length=160)
    channel_id: str | None = Field(default=None,pattern=r'^[0-9]{15,22}$')
    document: AnnouncementDocument
    is_template: bool = False
    expected_revision: int | None = Field(default=None,ge=1)


class PublishRequest(StrictModel):
    expected_revision: int = Field(ge=1)
    request_id: str = Field(pattern=r'^[a-zA-Z0-9-]{16,80}$')
    mode: Literal['create','update'] = 'create'
    target_id: str | None = Field(default=None,max_length=80)
    schedule_local: str | None = Field(default=None,max_length=30)
