"""Editable presentation blocks; functional controls and permissions stay server-owned."""
import copy
import hashlib
import json
import re
from datetime import datetime
import discord
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from typing import Literal
from services.announcement_components import safe_url
from services.ticket_avatars import avatar_source

KEYS = {
    'public:verification':'Accueil · Vérification',
    'public:contact_staff':'Accueil · Contact Staff',
    'public:support':'Accueil · Soutien',
    'public:moderation':'Accueil · Modération',
    'room:verification':'Ticket · Vérification',
    'room:contact_staff':'Ticket · Contact Staff',
    'room:summons':'Ticket · Convocation',
    'room:bubble':'Ticket · Bulle',
    'room:support':'Ticket · Soutien',
    'request:support':'Demande de soutien en attente',
    'review:support':'Demande de soutien traitée',
}
_cache = {}
VARIABLES={'membre':24,'interlocuteur':24,'traite_par':24,'date_traitement':40,'salon':95}
TOKEN=re.compile(r'\{(membre|interlocuteur|traite_par|date_traitement|salon)\}')


def values(row):
    def mention(value,fallback):
        return f'<@{value}>' if value and str(value).isascii() and str(value).isdigit() else fallback
    stamp='Décision en attente'
    try:
        if row.get('decided_at'):stamp=f"<t:{int(datetime.fromisoformat(row['decided_at']).timestamp())}:F>"
    except (ValueError,TypeError):pass
    return {'membre':mention(row.get('member_id'),'Membre à sélectionner'),
        'interlocuteur':mention(row.get('assigned_id'),'Non attribué'),
        'traite_par':mention(row.get('decision_by'),'Décision en attente'),
        'date_traitement':stamp,
        'salon':f"<#{row['channel_id']}>" if str(row.get('channel_id','')).isdigit() else 'Salon en préparation'}


def member_avatar(row):
    source=avatar_source(row.get('member_avatar_url'))
    if source:return source
    member_id=str(row.get('member_id','0'))
    index=(int(member_id)>>22)%6 if member_id.isdigit() else 0
    return f'https://cdn.discordapp.com/embed/avatars/{index}.png'


def render_text(text,row):
    replacements=values(row)
    return TOKEN.sub(lambda match:replacements[match.group(1)],text)



class Block(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kind:Literal['text','section','separator','image','link']='text'
    text:str=Field(default='',max_length=700)
    url:str=Field(default='',max_length=512)
    label:str=Field(default='',max_length=80)


class Panel(BaseModel):
    model_config=ConfigDict(extra='forbid')
    replace_heading:bool=False
    color:str=Field(default='#78618c',pattern=r'^#[0-9a-fA-F]{6}$')
    blocks:list[Block]=Field(default_factory=list,max_length=5)


def validate(panels):
    if set(panels)-set(KEYS):
        raise HTTPException(422,'Panneau inconnu.')
    result={}
    for key,value in panels.items():
        try:
            panel=Panel.model_validate(value)
        except ValidationError:
            raise HTTPException(422,"Vérifie les types de blocs, leurs champs et la couleur du panneau.") from None
        if sum(len((b.text+b.label).encode('utf-16-le'))//2 for b in panel.blocks)>700:
            raise HTTPException(422,'Limite de 700 caractères par panneau personnalisé, pour conserver les informations du dossier.')
        for b in panel.blocks:
            if b.kind in ('text','section') and not b.text.strip():
                raise HTTPException(422,'Un bloc texte ne peut pas être vide.')
            if b.kind in ('image','section') and b.url=='{avatar_membre}':
                if key.startswith('public:'):raise HTTPException(422,'L’avatar du membre est disponible seulement dans un ticket ou une demande.')
                continue
            if b.kind in ('image','section','link') and not safe_url(b.url,media=b.kind in ('image','section')):
                raise HTTPException(422,'Le média ou lien doit utiliser une adresse publique valide.')
            if b.kind=='link' and not b.label.strip():
                raise HTTPException(422,'Le bouton de lien doit avoir un libellé.')
        if panel.replace_heading and (not key.startswith('room:') or not any('{membre}' in b.text for b in panel.blocks if b.kind in ('text','section'))):
            raise HTTPException(422,'Un en-tête de ticket personnalisé doit contenir {membre}.')
        for b in panel.blocks:
            if key.startswith('public:') and TOKEN.search(b.text):
                raise HTTPException(422,'Un panneau public ne connaît pas encore le membre : utilisez les variables dans un ticket ou une demande.')
        # Budget the maximum expansion before Discord receives a message.
        expanded=sum(len((b.text+b.label).encode('utf-16-le'))//2 + sum(b.text.count('{'+name+'}')*max(0,size-len(name)-2) for name,size in VARIABLES.items()) for b in panel.blocks)
        if expanded>700:
            raise HTTPException(422,'Le texte, mentions comprises, dépasse la place disponible (700 caractères).')
        result[key]=panel.model_dump()
    return result


def configure(panels):
    global _cache
    _cache=copy.deepcopy(panels or {})


def replaces_heading(key):
    return bool(_cache.get(key,{}).get('replace_heading'))


def apply(box,key,*,replace=False,member_id=None,row=None):
    panel=_cache.get(key)
    if not panel or not panel.get('blocks'):
        return False
    if replace:
        box.clear_items()
    box.accent_colour=int(panel['color'][1:],16)
    for b in panel['blocks']:
        context=row or {'member_id':member_id}
        text=render_text(b['text'],context)
        media_url=member_avatar(context) if b['url']=='{avatar_membre}' else b['url']
        if b['kind']=='text':box.add_item(discord.ui.TextDisplay(text))
        elif b['kind']=='section':box.add_item(discord.ui.Section(discord.ui.TextDisplay(text),accessory=discord.ui.Thumbnail(media_url)))
        elif b['kind']=='separator':box.add_item(discord.ui.Separator())
        elif b['kind']=='image':box.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(media_url,description=text or None)))
        elif b['kind']=='link':box.add_item(discord.ui.ActionRow(discord.ui.Button(style=discord.ButtonStyle.link,label=b['label'],url=b['url'])))
    return True


def revision(key):
    return hashlib.sha256(json.dumps(_cache.get(key,{}),sort_keys=True).encode()).hexdigest()[:16]
