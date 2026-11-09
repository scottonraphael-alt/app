"""OasisGame tokens never authorize CinéStream; channel checks use Discord's live cache."""
import hashlib
import jwt
from fastapi import HTTPException
from routers import activity

AUDIENCE = 'oasis-games'
KARAOKE_CHANNEL_ID = '1569069812804751431'


def decode(token):
    if not activity.ACTIVITY_TOKEN_KEY:
        return None
    try:
        return jwt.decode(token, activity.ACTIVITY_TOKEN_KEY, algorithms=['HS256'], audience=AUDIENCE)
    except jwt.PyJWTError:
        return None


def room_id(instance):
    return 'og_'+hashlib.sha256(instance.encode()).hexdigest()[:40]


def require_instance(claims, instance):
    if instance.startswith('og_') and claims.get('aud') != AUDIENCE:
        raise HTTPException(403, 'Une session OasisGame est nécessaire.')
    if claims.get('aud') == AUDIENCE and claims.get('instance_id') != instance:
        raise HTTPException(403, 'Cette session appartient à une autre partie OasisGame.')


def current_voice_channel(uid):
    from services.moderation_bot import moderation_client
    if not moderation_client.is_ready():
        raise HTTPException(503, 'La vérification du salon vocal est momentanément indisponible.')
    guild = moderation_client.get_guild(int(activity.DISCORD_GUILD_ID))
    member = guild.get_member(int(uid)) if guild else None
    actual = getattr(getattr(getattr(member, 'voice', None), 'channel', None), 'id', None)
    return str(actual)


def require_karaoke_channel(claims):
    # Both the Activity channel and the member’s real voice presence must match.
    if str(claims.get('channel_id')) != KARAOKE_CHANNEL_ID or current_voice_channel(claims['sub']) != KARAOKE_CHANNEL_ID:
        raise HTTPException(403, f'Le karaoké est disponible uniquement dans le salon <#{KARAOKE_CHANNEL_ID}>. Rejoins ce salon puis ouvre OasisGame depuis celui-ci.')
