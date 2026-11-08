"""Small authenticated relay: the Anthropic key never leaves IRIS."""
import asyncio
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone

from anthropic import AsyncAnthropic
from fastapi import APIRouter, Header, HTTPException, Request
import config
from database import db
from services.karaoke_arbitration import VERSION, SYSTEM, TOOL, validate_rows, validate_decisions
from services.anthropic_runtime import generation_options, log_response

router = APIRouter(prefix='/karaoke/preparation', tags=['karaoke-preparation'])
SLOTS = asyncio.Semaphore(2)
logger = logging.getLogger(__name__)


def authorize(authorization):
    secret = os.getenv('KARAOKE_PREPARATION_SECRET', '')
    if len(secret) < 32:
        raise HTTPException(503, 'Relais de préparation non configuré.')
    if not hmac.compare_digest(authorization.encode(), ('Bearer '+secret).encode()):
        raise HTTPException(401, 'Accès refusé.')
    if not config.ANTHROPIC_API_KEY:
        raise HTTPException(503, 'Arbitrage Anthropic non configuré.')


@router.get('/status')
async def status(authorization: str = Header('')):
    authorize(authorization)
    return {'ready': True, 'version': VERSION,
            'model': os.getenv('KARAOKE_ARBITRATION_MODEL', config.TICKET_SUMMARY_MODEL)}


@router.post('/arbitrate')
async def arbitrate(request: Request, authorization: str = Header('')):
    authorize(authorization)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 50_000:
            raise HTTPException(413, 'Lot trop volumineux.')
    try:
        data = json.loads(raw)
        if set(data) != {'language', 'rows'} or not isinstance(data['language'], str) or len(data['language']) > 10:
            raise ValueError('Lot hors schéma.')
        validate_rows(data['rows'])
    except (ValueError, TypeError):
        raise HTTPException(422, 'Candidats invalides.')
    model = os.getenv('KARAOKE_ARBITRATION_MODEL', config.TICKET_SUMMARY_MODEL)
    key = hashlib.sha256(json.dumps([VERSION, model, data], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    async with SLOTS:
        cached = await db.karaoke_preparation_arbitrations.find_one({'_id': key})
        if cached and cached.get('decisions'):
            return {'version': VERSION, 'model': model, 'decisions': cached['decisions']}
        try:
            async with asyncio.timeout(120):
                async with AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY, max_retries=1, timeout=110) as client:
                    response = await client.messages.create(model=model, max_tokens=6000,
                        **generation_options(model), system=SYSTEM,
                        tools=[TOOL], tool_choice={'type': 'tool', 'name': TOOL['name']},
                        messages=[{'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}])
            blocks = [b for b in response.content if b.type == 'tool_use' and b.name == TOOL['name']]
            if response.stop_reason != 'tool_use' or len(blocks) != 1:
                raise ValueError('Arbitrage tronqué.')
            decisions = validate_decisions(data['rows'], blocks[0].input)
            log_response('karaoke_preparation_arbitration', model, response)
        except Exception as error:
            logger.warning('Arbitrage karaoké interrompu (%s).', type(error).__name__)
            raise HTTPException(502, 'Arbitrage indisponible ou incomplet ; candidats conservés sur le Mac.')
        await db.karaoke_preparation_arbitrations.update_one({'_id': key}, {'$set': {
            'version': VERSION, 'model': model, 'candidates': data, 'decisions': decisions,
            'created_at': datetime.now(timezone.utc)}}, upsert=True)
    return {'version': VERSION, 'model': model, 'decisions': decisions}
