"""Actions des tickets dans le journal central d'Iris ; jamais de copie des échanges."""
import asyncio
import logging
from functools import wraps

from fastapi import HTTPException, Request

from database import db
from models.ticket import AuthenticatedHelper
from services.audit_service import log_auth_event

logger = logging.getLogger(__name__)


async def log_ticket_action(event, request, helper, ticket=None, status=200, details=None):
    ticket = ticket or {}
    member = ticket.get('member') or {}
    context = {'ticket_id': ticket.get('id'), 'member_id': member.get('id'),
               'member_username': member.get('display_name') or member.get('username')}
    context.update(details or {})
    try:
        await asyncio.wait_for(log_auth_event(event, request, helper, status, context), 5)
    except Exception:
        logger.exception('Journal des tickets indisponible : %s', event)


def audit_action(event, status=200):
    def decorate(function):
        @wraps(function)
        async def audited(*args, **kwargs):
            request = next((v for v in kwargs.values() if isinstance(v, Request)), None)
            helper = next((v for v in kwargs.values() if isinstance(v, AuthenticatedHelper)), None)
            ticket_id = kwargs.get('ticket_id')
            ticket = None
            if ticket_id:
                ticket = await db.tickets.find_one({'id': ticket_id, 'demo_ticket': {'$ne': True}},
                    {'_id':0,'id':1,'member':1,'status':1,'assigned_helper.id':1})
            details = {}
            if kwargs.get("note_id"):
                details["note_id"] = kwargs["note_id"]
            actual_event = event
            data = kwargs.get('input_data')
            if data is not None and hasattr(data, 'model_dump'):
                fields = data.model_dump(exclude_none=True)
                if event == 'ticket.updated' and fields.get('status') and fields['status'] != (ticket or {}).get('status'):
                    actual_event = 'ticket.archived' if fields['status'] == 'archived' else 'ticket.reactivated'
                    if actual_event == 'ticket.archived':
                        details['previous_helper_id'] = ((ticket or {}).get('assigned_helper') or {}).get('id')
                details['fields'] = list(fields)
                details['field_lengths'] = {key: len(value) for key,value in fields.items() if key in {'notes','vocal_summary','person_triggers','content','title'} and isinstance(value,str)}
                for key in ('status','follow_up_status','helper_id'):
                    if key in fields:
                        details[key] = fields[key]
                if event == 'ticket.assignment.changed':
                    details['previous_helper_id'] = ((ticket or {}).get('assigned_helper') or {}).get('id')
                    details['helper_id'] = getattr(data, 'helper_id', None)
            for key in ('page','search_page','from_day','to_day'):
                if kwargs.get(key) is not None:
                    details[key] = str(kwargs[key])
            if 'q' in kwargs:
                details['query_length'] = len(kwargs['q'] or '')
            try:
                result = await function(*args, **kwargs)
            except Exception as error:
                await log_ticket_action(actual_event+'.failed', request, helper, ticket, getattr(error,'status_code',500), details)
                raise
            if event == 'ticket.note.created' and hasattr(result, 'id'):
                details['note_id'] = result.id
            if event == 'ticket.created' and isinstance(result, dict):
                ticket = result
            if isinstance(result, dict):
                for key in ('total','ticket_count','helper_count'):
                    if key in result:
                        details[key] = result[key]
            await log_ticket_action(actual_event, request, helper, ticket, status, details)
            return result
        return audited
    return decorate
