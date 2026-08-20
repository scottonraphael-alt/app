from pydantic import BaseModel, Field


class ChannelArchiveAttachment(BaseModel):
    id: str
    filename: str
    url: str
    local_url: str | None = None
    content_type: str | None = None


class ChannelArchiveAuthor(BaseModel):
    id: str
    username: str
    display_name: str
    avatar_url: str | None = None
    is_bot: bool = False


class ChannelArchiveMessage(BaseModel):
    id: str
    content: str
    timestamp: str
    author: ChannelArchiveAuthor
    attachments: list[ChannelArchiveAttachment] = Field(default_factory=list)
    embeds: list[dict] = Field(default_factory=list)
    components: list[dict] = Field(default_factory=list)
    application_id: str | None = None
    webhook_id: str | None = None


class ChannelArchiveCreate(BaseModel):
    channel_id: str
    title: str | None = None


class ChannelArchiveSummary(BaseModel):
    id: str
    title: str
    channel_id: str
    channel_name: str
    status: str
    message_count: int
    local_attachment_count: int
    created_by: str
    created_at: str
    updated_at: str
    last_synced_at: str


class ChannelArchiveDetail(ChannelArchiveSummary):
    transcript: list[ChannelArchiveMessage] = Field(default_factory=list)
