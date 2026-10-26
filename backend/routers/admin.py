from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from database import db
from models.ticket import (
    AdminHelperOverview,
    AdminOverview,
    AuthenticatedHelper,
    HelperIdentity,
    TicketAssignmentUpdate,
    TicketDetail,
    TicketSummary,
)
from services.auth_service import current_admin, current_helper
from services.discord_service import DiscordService
from services.ticket_assignment import ticket_helper_role_ids
from services.ticket_avatars import cache_avatar


router = APIRouter(prefix="/admin", tags=["admin"])


async def ticket_or_404(ticket_id: str) -> dict:
    ticket = await db.tickets.find_one(
        {"id": ticket_id, "demo_ticket": {"$ne": True}},
        {"_id": 0},
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket Iris introuvable.")
    return ticket


@router.get("/helpers", response_model=list[HelperIdentity])
async def list_authorized_helpers(
    _: AuthenticatedHelper = Depends(current_admin),
) -> list[HelperIdentity]:
    return await DiscordService().fetch_helpers(ticket_helper_role_ids())


@router.get("/overview", response_model=AdminOverview)
async def admin_overview(
    _: AuthenticatedHelper = Depends(current_admin),
) -> AdminOverview:
    helpers = await DiscordService().fetch_helpers(ticket_helper_role_ids())
    profiles = await db.helper_profiles.find({}, {"_id": 0}).to_list(1000)
    profiles_by_helper = {profile["helper_id"]: profile for profile in profiles}
    tickets = await db.tickets.find(
        {"demo_ticket": {"$ne": True}},
        {"_id": 0, "transcript": 0, "notes": 0, "vocal_summary": 0},
    ).sort("updated_at", -1).to_list(250)
    overview_items: list[AdminHelperOverview] = []
    for helper in helpers:
        assigned = [
            ticket
            for ticket in tickets
            if (ticket.get("assigned_helper") or {}).get("id") == helper.id
        ]
        overview_items.append(
            AdminHelperOverview(
                helper=helper,
                assigned_count=len(assigned),
                active_count=sum(ticket["status"] == "active" for ticket in assigned),
                tickets=assigned,
                triggers=profiles_by_helper.get(helper.id, {}).get("triggers", ""),
                profile_updated_at=profiles_by_helper.get(helper.id, {}).get("updated_at"),
            )
        )
    return AdminOverview(
        total_helpers=len(helpers),
        active_tickets=sum(ticket["status"] == "active" for ticket in tickets),
        unassigned_tickets=sum(not ticket.get("assigned_helper") for ticket in tickets),
        helpers=overview_items,
    )


@router.patch("/tickets/{ticket_id}/assignment", response_model=TicketDetail)
async def assign_ticket_helper(
    ticket_id: str,
    input_data: TicketAssignmentUpdate,
    _: AuthenticatedHelper = Depends(current_admin),
) -> TicketDetail:
    ticket = await ticket_or_404(ticket_id)
    assigned_helper: HelperIdentity | None = None
    if input_data.helper_id:
        helpers = await DiscordService().fetch_helpers(ticket_helper_role_ids())
        assigned_helper = next(
            (helper for helper in helpers if helper.id == input_data.helper_id),
            None,
        )
        if not assigned_helper:
            raise HTTPException(status_code=422, detail="Le helper choisi n’est pas autorisé.")
    if assigned_helper:
        assigned_helper.avatar_url = await cache_avatar(assigned_helper.avatar_url)
    timestamp = datetime.now(timezone.utc).isoformat()
    updates = {"assigned_helper": assigned_helper.model_dump() if assigned_helper else None, "updated_at": timestamp}
    if input_data.helper_id != (ticket.get("assigned_helper") or {}).get("id"):
        # Le nouvel interlocuteur dispose d'une semaine avant le prochain rappel.
        updates["last_helper_update_at"] = timestamp
    await db.tickets.update_one(
        {"id": ticket_id, "demo_ticket": {"$ne": True}},
        {"$set": updates},
    )
    return await ticket_or_404(ticket_id)


@router.delete("/tickets/{ticket_id}", status_code=204)
async def delete_ticket_as_admin(
    ticket_id: str,
    _: AuthenticatedHelper = Depends(current_admin),
) -> None:
    ticket = await ticket_or_404(ticket_id)
    # Éviter que le scanner recrée un dossier supprimé tant que son salon existe.
    await db.ticket_import_exclusions.update_one(
        {"_id": ticket["channel_id"]},
        {"$set": {"excluded_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    await db.tickets.delete_one({"id": ticket_id, "demo_ticket": {"$ne": True}})


@router.post("/ticket-reminders/test")
async def send_test_ticket_reminder(
    _: AuthenticatedHelper = Depends(current_admin),
) -> dict:
    from services.ticket_reminders import test_reminder
    return await test_reminder()
