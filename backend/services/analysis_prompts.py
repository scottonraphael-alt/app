"""Editable analysis instructions; technical output contracts stay in the callers."""
from database import db
from fastapi import HTTPException


def default(key):
    from services.ai_summary_service import SYSTEM_PROMPT
    from services.verification_advisory import DEFAULT_PROMPT
    from services.ticket_copilot import SUMMARY_SYSTEM
    defaults={'ticket_summary':SYSTEM_PROMPT,'verification':DEFAULT_PROMPT,'copilot':SUMMARY_SYSTEM}
    if key not in defaults:raise HTTPException(404,'Prompt inconnu.')
    return defaults[key]


async def resolve(key,fallback):
    row=await db.ai_configuration.find_one({'_id':'analysis-prompt:'+key})
    return row['prompt'] if row else fallback
