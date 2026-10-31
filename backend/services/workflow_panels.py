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
    'anonymous:review':'Messages anonymes · Validation Staff',
    'form:verification':'Vérification · Formulaire complet (fil)',
    'staff:verification':'Vérification · Mini-panneau Staff (salon)',
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
VARIABLES={'membre_id':20,'membre_username':32,'membre':24,'interlocuteur':24,'traite_par':24,'date_traitement':40,'salon':95,'avis_ia':1000,'identifiant_anonyme':11,'message_anonyme':3000,'motif':1000,'triggers':1000,'motif_refus':1000,'statut':40,'reponses_formulaire':2200}
TOKEN=re.compile(r'\{('+ '|'.join(VARIABLES) +r')\}')


def values(row):
    def mention(value,fallback):
        return f'<@{value}>' if value and str(value).isascii() and str(value).isdigit() else fallback
    stamp='Décision en attente'
    try:
        if row.get('decided_at'):stamp=f"<t:{int(datetime.fromisoformat(row['decided_at']).timestamp())}:F>"
    except (ValueError,TypeError):pass
    def short(value,units):
        return str(value or 'Non renseigné').encode('utf-16-le')[:units*2].decode('utf-16-le','ignore')
    answers=row.get('answers') or {}
    fields=[('name','👤 Prénom / pseudo',80),('age','🎂 Tranche d’âge',24),('reason','🌱 Motif de venue',500),('psychiatry','💬 Avis sur la psychiatrie',1300)]
    response='\n'.join('### '+label+'\n```\n'+short(answers.get(key),limit).strip().replace('`','ˋ')+'\n```' for key,label,limit in fields)
    response+='\n-# '+('✅ Règlement accepté : Oui' if answers.get('rules') else '⚠️ Règlement accepté : Non renseigné')
    return {'membre_id':str(row.get('member_id') or 'ID indisponible'),'membre_username':str(row.get('member_username') or (row.get('member') or {}).get('username') or 'Pseudo indisponible')[:32],
        'motif':short(row.get('reason'),1000),'triggers':short(row.get('triggers'),1000),
        'motif_refus':short(row.get('decision_reason') or row.get('reason'),1000),
        'statut':short(row.get('status_label') or {'waiting':'En attente','claimed':'Pris en charge','pending':'En attente','approved':'Publication en cours','published':'Publié','rejected':'Refusé','open':'Ouvert','suspended':'Suspendu','restricted':'Accès restreint','archived':'Archivé'}.get(row.get('status'),'À vérifier'),40),
        'reponses_formulaire':response,
        'identifiant_anonyme':str(row.get('alias') or 'ANO-XXXX-XX'),'message_anonyme':str(row.get('text') or ''),
        'avis_ia':str(row.get('advisory') or 'Préavis IA non généré. Une lecture humaine reste nécessaire.').encode('utf-16-le')[:2000].decode('utf-16-le','ignore'),
        'membre':mention(row.get('member_id'),'Membre à sélectionner'),
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
    text:str=Field(default='',max_length=4000)
    url:str=Field(default='',max_length=512)
    label:str=Field(default='',max_length=80)


class Panel(BaseModel):
    model_config=ConfigDict(extra='forbid')
    replace_heading:bool=False
    color:str=Field(default='#78618c',pattern=r'^#[0-9a-fA-F]{6}$')
    blocks:list[Block]=Field(default_factory=list,max_length=5)


def text_limit(key):
    # Reserve room for the mandatory restriction notice beneath the selector.
    return 3700 if key in ('room:verification','room:contact_staff','room:bubble','room:summons','review:support') else 4000


def expanded_size(blocks):
    return sum(len(b.text.encode('utf-16-le'))//2 + sum(b.text.count('{'+name+'}')*max(0,size-len(name)-2) for name,size in VARIABLES.items()) for b in blocks if b.kind in ('text','section'))


def form_answer_limit():
    panel=_cache.get('form:verification') or {}
    if not panel.get('blocks'):return 1500
    size=expanded_size(Panel.model_validate(panel).blocks)
    # Reserve labels, status, actions and decisions; allow two UTF-16 units per character.
    return max(100,min(1500,(4000-size-1000)//8))


def validate(panels):
    if set(panels)-set(KEYS):
        raise HTTPException(422,'Panneau inconnu.')
    result={}
    for key,value in panels.items():
        try:
            panel=Panel.model_validate(value)
        except ValidationError:
            raise HTTPException(422,"Vérifie les types de blocs, leurs champs et la couleur du panneau.") from None
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
        if key=='anonymous:review' and panel.blocks:
            if not any('{message_anonyme}' in b.text for b in panel.blocks if b.kind in ('text','section')):
                raise HTTPException(422,'Le panneau de validation doit contenir {message_anonyme} pour permettre sa lecture avant décision.')
            if any(any('{'+name+'}' in b.text for name in ('membre','membre_id','membre_username','interlocuteur','avatar_membre','salon','avis_ia','reponses_formulaire')) or b.url=='{avatar_membre}' for b in panel.blocks):
                raise HTTPException(422,'Utilise les variables anonymes, sans identité ni avatar du membre.')
        for b in panel.blocks:
            if '{reponses_formulaire}' in b.text and key!='form:verification':raise HTTPException(422,'Les réponses du formulaire sont disponibles dans le formulaire complet.')
            if '{avis_ia}' in b.text and key not in ('form:verification','staff:verification'):raise HTTPException(422,'Le préavis IA est disponible dans le formulaire complet et le mini-panneau de vérification.')
            if key.startswith('public:') and TOKEN.search(b.text):
                raise HTTPException(422,'Un panneau public ne connaît pas encore le membre : utilisez les variables dans un ticket ou une demande.')
        # Budget the maximum expansion before Discord receives a message.
        expanded=expanded_size(panel.blocks)
        limit=text_limit(key)
        if expanded>limit:
            raise HTTPException(422,f'Ce panneau dispose de {limit} caractères, variables comprises. Le reste est réservé aux informations automatiques Discord.')
        for b in panel.blocks:
            if b.kind=='image' and len(b.text.encode('utf-16-le'))//2>1024:
                raise HTTPException(422,'La description d’une image est limitée à 1 024 caractères.')
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
    return hashlib.sha256(json.dumps({'layout':7,'panel':_cache.get(key,{})},sort_keys=True).encode()).hexdigest()[:16]
