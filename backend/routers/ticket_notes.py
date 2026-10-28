"""Notes internes d'un ticket (/api/ticket-notes) : visibles des helpers seulement, jamais envoyées au membre."""
import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator

from database import db
from models.ticket import AuthenticatedHelper
from services.auth_service import current_ticket_helper, is_admin_helper
from services.ticket_extras import author_name, now_iso, require_ticket

router = APIRouter(prefix="/ticket-notes", tags=["ticket-notes"])
ID = Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")


class InternalNoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=4000)

    @field_validator("body")
    @classmethod
    def _body(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("La note ne peut pas être vide.")
        return value


def _view(doc: dict) -> dict:
    return {k: doc[k] for k in ("id", "ticket_id", "body", "author_id", "author_name", "created_at")}


@router.get("/{ticket_id}")
async def list_notes(ticket_id: str = ID, _: AuthenticatedHelper = Depends(current_ticket_helper)) -> dict:
    await require_ticket(ticket_id)
    items = await db.ticket_internal_notes.find({"ticket_id": ticket_id}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"items": [_view(i) for i in items]}


@router.post("/{ticket_id}", status_code=201)
async def add_note(payload: InternalNoteIn, ticket_id: str = ID,
                   helper: AuthenticatedHelper = Depends(current_ticket_helper)) -> dict:
    await require_ticket(ticket_id)
    doc = {"id": str(uuid4()), "ticket_id": ticket_id, "body": payload.body, "author_id": helper.id,
           "author_name": author_name(helper), "created_at": now_iso()}
    await db.ticket_internal_notes.insert_one(dict(doc))
    return _view(doc)


@router.delete("/{ticket_id}/{note_id}", status_code=204)
async def delete_note(ticket_id: str = ID, note_id: str = Path(pattern=r"^[A-Za-z0-9_-]{1,64}$"),
                      helper: AuthenticatedHelper = Depends(current_ticket_helper)) -> None:
    note = await db.ticket_internal_notes.find_one({"id": note_id, "ticket_id": ticket_id}, {"_id": 0})
    if not note:
        raise HTTPException(status_code=404, detail="Note introuvable.")
    if note["author_id"] != helper.id and not await is_admin_helper(helper.id):
        raise HTTPException(status_code=403, detail="Seul l'auteur ou un coordinateur peut supprimer cette note.")
    await db.ticket_internal_notes.delete_one({"id": note_id})
