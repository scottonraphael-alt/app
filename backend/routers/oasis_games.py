"""Dedicated OAuth entry point for the public OasisGame Discord application."""
import os
import time
import httpx
import jwt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from routers import activity
from services.oasis_games_auth import AUDIENCE, KARAOKE_CHANNEL_ID, room_id

router = APIRouter(prefix='/games', tags=['oasis-games'])


class GameTokenRequest(BaseModel):
    code: str = Field(min_length=1, max_length=4096)
    guild_id: str
    instance_id: str = Field(min_length=1, max_length=128)
    channel_id: str | None = Field(default=None, pattern=r'^\d{17,20}$')


@router.get('/config')
async def configuration():
    ident = os.getenv('OASISGAME_DISCORD_CLIENT_ID', '')
    return {'configured': bool(ident and os.getenv('OASISGAME_DISCORD_CLIENT_SECRET') and activity.ACTIVITY_TOKEN_KEY),
            'client_id': ident, 'karaoke_channel_id': KARAOKE_CHANNEL_ID}


@router.post('/token')
async def token(payload: GameTokenRequest):
    ident, secret = os.getenv('OASISGAME_DISCORD_CLIENT_ID'), os.getenv('OASISGAME_DISCORD_CLIENT_SECRET')
    if not ident or not secret or not activity.ACTIVITY_TOKEN_KEY:
        raise HTTPException(503, 'OasisGame doit encore être configuré sur le serveur.')
    if payload.guild_id != str(activity.DISCORD_GUILD_ID):
        raise HTTPException(403, 'OasisGame est réservé aux membres de L’Oasis.')
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(activity.DISCORD_API+'/oauth2/token', data={
            'client_id':ident,'client_secret':secret,'grant_type':'authorization_code','code':payload.code})
        if response.status_code != 200:
            raise HTTPException(401, 'Authentification OasisGame refusée.')
        access = response.json()['access_token']
        response = await client.get(activity.DISCORD_API+f'/users/@me/guilds/{activity.DISCORD_GUILD_ID}/member',headers={'Authorization':'Bearer '+access})
        if response.status_code != 200:
            raise HTTPException(403, 'OasisGame est réservé aux membres de L’Oasis.')
        member = response.json()
    user = member.get('user') or {}
    if not user.get('id'):
        raise HTTPException(401, 'Compte Discord introuvable.')
    name = (member.get('nick') or user.get('global_name') or user.get('username') or 'Joueur')[:32]
    instance = room_id(payload.instance_id)
    signed = jwt.encode({'sub':str(user['id']), 'name':name, 'aud':AUDIENCE, 'can_control':True,
                        'instance_id':instance, 'channel_id':payload.channel_id, 'exp':int(time.time())+activity.VIDEO_TOKEN_TTL},
                       activity.ACTIVITY_TOKEN_KEY, algorithm='HS256')
    return {'access_token':access,'video_token':signed,'user_id':str(user['id']),'user_name':name,
            'instance_id':instance,'can_control':True,'karaoke_channel_id':KARAOKE_CHANNEL_ID}
