"""Editable presentation blocks; functional controls and permissions stay server-owned."""
import copy
import discord
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from typing import Literal
from services.announcement_components import safe_url

KEYS = {
    'public:verification':'Accueil · Vérification',
    'public:contact_staff':'Accueil · Contact Staff',
    'public:support':'Accueil · Soutien',
    'room:verification':'Ticket · Vérification',
    'room:contact_staff':'Ticket · Contact Staff',
    'room:summons':'Ticket · Convocation',
    'room:bubble':'Ticket · Bulle',
    'room:support':'Ticket · Soutien',
    'request:support':'Demande de soutien en attente',
    'review:support':'Demande de soutien traitée',
}
_cache = {}


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
            if b.kind in ('image','section','link') and not safe_url(b.url,media=b.kind in ('image','section')):
                raise HTTPException(422,'Le média ou lien doit utiliser une adresse publique valide.')
            if b.kind=='link' and not b.label.strip():
                raise HTTPException(422,'Le bouton de lien doit avoir un libellé.')
        if panel.replace_heading and (not key.startswith('room:') or not any('{membre}' in b.text for b in panel.blocks if b.kind in ('text','section'))):
            raise HTTPException(422,'Un en-tête de ticket personnalisé doit contenir {membre}.')
        # Reserve the maximum expansion of each supported mention.
        expanded=sum(len((b.text+b.label).encode('utf-16-le'))//2 + b.text.count('{membre}')*16 for b in panel.blocks)
        if expanded>700:
            raise HTTPException(422,'Le texte, mentions comprises, dépasse la place disponible (700 caractères).')
        result[key]=panel.model_dump()
    return result


def configure(panels):
    global _cache
    _cache=copy.deepcopy(panels or {})


def replaces_heading(key):
    return bool(_cache.get(key,{}).get('replace_heading'))


def apply(box,key,*,replace=False,member_id=None):
    panel=_cache.get(key)
    if not panel or not panel.get('blocks'):
        return False
    if replace:
        box.clear_items()
    box.accent_colour=int(panel['color'][1:],16)
    for b in panel['blocks']:
        text=b['text']
        if member_id is not None and str(member_id).isascii() and str(member_id).isdigit():
            text=text.replace('{membre}',f'<@{member_id}>')
        if b['kind']=='text':box.add_item(discord.ui.TextDisplay(text))
        elif b['kind']=='section':box.add_item(discord.ui.Section(discord.ui.TextDisplay(text),accessory=discord.ui.Thumbnail(b['url'])))
        elif b['kind']=='separator':box.add_item(discord.ui.Separator())
        elif b['kind']=='image':box.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(b['url'],description=b['text'] or None)))
        elif b['kind']=='link':box.add_item(discord.ui.ActionRow(discord.ui.Button(style=discord.ButtonStyle.link,label=b['label'],url=b['url'])))
    return True
