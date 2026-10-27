"""Bounded output settings and diagnostics without prompts or private responses."""
import asyncio
import hashlib
import logging
import time

from anthropic import APIError
from fastapi import HTTPException

logger=logging.getLogger(__name__)


_MODEL_LIMITS={}
_MODEL_LOCK=asyncio.Lock()


async def maximum_output_tokens(client,model):
    """Use the actual model ceiling, not a small application-defined token budget."""
    key=(hashlib.sha256(str(getattr(client,'api_key','')).encode()).hexdigest(),model)
    cached=_MODEL_LIMITS.get(key)
    if cached and cached[0]>time.monotonic():return cached[1]
    async with _MODEL_LOCK:
        cached=_MODEL_LIMITS.get(key)
        if cached and cached[0]>time.monotonic():return cached[1]
        try:info=await client.models.retrieve(model,timeout=15)
        except APIError as error:
            if cached:return cached[1]
            raise provider_failure(error) from None
        limit=getattr(info,'max_tokens',None)
        if isinstance(limit,bool) or not isinstance(limit,int) or limit<=0:
            raise HTTPException(503,'Anthropic ne fournit pas la capacité de sortie de ce modèle. L’équipe doit vérifier sa configuration.')
        _MODEL_LIMITS[key]=(time.monotonic()+3600,limit)
        return limit


def generation_options(model,*,research=False):
    # Only opt in for documented model families. Older/custom models keep their defaults.
    name=model.lower()
    supported=any(name==family or name.startswith(family+'-20') for family in (
        'claude-haiku-5-5','claude-sonnet-5','claude-sonnet-5-5','claude-opus-5'))
    if not supported:return {}
    options={'output_config':{'effort':'low'}}
    if not research:
        options['thinking']={'type':'between_tools' if name.startswith('claude-sonnet-5-5') else 'disabled'}
    return options


def log_response(operation,model,response):
    logger.info('Anthropic operation=%s model=%s stop=%s output_tokens=%s request_id=%s',
        operation,model,getattr(response,'stop_reason',None),getattr(getattr(response,'usage',None),'output_tokens',None),
        getattr(response,'_request_id',None))


def provider_failure(error):
    code=getattr(error,'status_code',None)
    logger.warning('Anthropic failed type=%s status=%s request_id=%s',type(error).__name__,code,getattr(error,'request_id',None))
    if code in (401,403):detail='L’accès Anthropic est refusé. L’équipe doit vérifier la clé et les autorisations du compte.'
    elif code==429:detail='La limite Anthropic est atteinte. Réessaie dans quelques instants.'
    elif code in (400,404):detail='Anthropic a refusé la configuration de la requête. L’équipe doit vérifier le modèle et les outils activés.'
    else:detail='Anthropic est momentanément indisponible ou a interrompu la connexion. Réessaie plus tard.'
    return HTTPException(503,detail)


def incomplete_response(reason):
    if reason=='max_tokens':detail='La réponse IA a atteint la capacité maximale du modèle. Réessaie avec une demande plus précise.'
    elif reason=='model_context_window_exceeded':detail='Le dossier ou la recherche dépasse la capacité du modèle IA.'
    elif reason=='refusal':detail='L’IA n’a pas pu répondre à cette demande. Reformule-la comme une demande d’informations générales.'
    else:detail='La réponse IA n’a pas pu être terminée. Réessaie plus tard.'
    return HTTPException(503,detail)
