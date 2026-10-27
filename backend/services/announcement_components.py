"""Discord V2 compiler: explicit mentions, public media URLs, server-owned files only."""
import ipaddress
import re
from urllib.parse import urlsplit
from models.announcement import AnnouncementDocument

MAX_FILES_SIZE=10*1024*1024


def safe_url(value, *, media=False):
    try:
        parsed=urlsplit(value)
        if parsed.scheme not in ({'https'} if media else {'http','https'}) or not parsed.hostname or parsed.username or parsed.password:return False
        host=parsed.hostname.lower().rstrip('.')
        if host=='localhost' or host.endswith(('.localhost','.local','.internal')):return False
        try:
            if not ipaddress.ip_address(host).is_global:return False
        except ValueError:
            # Refuse non-canonical numeric addresses as well (127.1, 2130706433).
            if re.fullmatch(r"[0-9.]+",host) or host.startswith("0x"):return False
        return bool(parsed.netloc) and not any(ord(c)<32 for c in value)
    except ValueError:return False


def asset_ids(document):
    ids=set()
    for group in document['groups']:
        for block in group['blocks']:
            if block['kind']=='file' and block.get('file_asset_id'):ids.add(block['file_asset_id'])
            if block['kind']=='section' and block.get('accessory','thumbnail')=='thumbnail' and block.get('thumbnail',{}).get('asset_id'):ids.add(block['thumbnail']['asset_id'])
            if block['kind']=='gallery':ids.update(item['asset_id'] for item in block.get('items',[]) if item.get('asset_id'))
    return ids


def compile_document(document, assets):
    doc=document.model_dump() if isinstance(document,AnnouncementDocument) else AnnouncementDocument.model_validate(document).model_dump()
    errors=[]; text_count=0; component_count=0; used={}
    def error(label,message):errors.append(f'{label} : {message}')
    def text(value,label):
        nonlocal text_count,component_count
        component_count+=1;text_count+=len(value.encode('utf-16-le'))//2
        if not value.strip():error(label,'le texte est vide.')
        return {'type':10,'content':value}
    def media(value,label,thumbnail=False):
        asset=None
        if value.get('asset_id'):
            asset=assets.get(value['asset_id'])
            if not asset:error(label,'le fichier est introuvable.')
            else:
                used[asset['id']]=asset
                kind=asset.get('content_type','')
                if not kind.startswith(('image/','video/')) or (thumbnail and not kind.startswith('image/')):error(label,'choisissez une image' if thumbnail else 'choisissez une image ou une vidéo')
            url=f"attachment://{asset['discord_filename']}" if asset else ''
            if value.get('url'):error(label,'choisissez un fichier ou une URL, pas les deux.')
        else:
            url=value.get('url','')
            if not safe_url(url,media=True):error(label,'une URL HTTPS publique est nécessaire.')
        result={'media':{'url':url},'spoiler':value.get('spoiler',False)}
        if value.get('description'):result['description']=value['description']
        return result
    def button(value,label):
        nonlocal component_count
        component_count+=1
        if not value['label'].strip():error(label,'le libellé du bouton est vide.')
        if not safe_url(value['url']):error(label,'le lien doit utiliser HTTP ou HTTPS avec une adresse publique.')
        result={'type':2,'style':5,'label':value['label'],'url':value['url'],'disabled':value['disabled']}
        if value['emoji']:
            match=re.fullmatch(r'<(a?):[a-zA-Z0-9_]+:([0-9]{15,22})>',value['emoji'])
            result['emoji']={'id':match[2],'animated':bool(match[1])} if match else {'name':value['emoji']}
        return result
    components=[]
    for gi,group in enumerate(doc['groups'],1):
        children=[]
        if not group['blocks']:error(f'Panneau {gi}','ajoutez au moins un bloc.')
        for bi,block in enumerate(group['blocks'],1):
            label=f'Panneau {gi}, bloc {bi}'
            kind=block['kind']
            if kind=='text':item=text(block['text'],label)
            elif kind=='section':
                component_count+=1
                values=block['texts']
                if not values:error(label,'la section nécessite un à trois textes.')
                texts=[text(value,label) for value in values]
                if block['accessory']=='button':accessory=button(block['button'],label)
                else:component_count+=1;accessory={'type':11,**media(block['thumbnail'],label,True)}
                item={'type':9,'components':texts,'accessory':accessory}
            elif kind=='gallery':
                component_count+=1
                if not block['items']:error(label,'ajoutez au moins un média.')
                item={'type':12,'items':[media(value,label) for value in block['items']]}
            elif kind=='separator':component_count+=1;item={'type':14,'divider':block['divider'],'spacing':block['spacing']}
            elif kind=='buttons':
                component_count+=1
                if not block['buttons']:error(label,'ajoutez au moins un bouton de lien.')
                item={'type':1,'components':[button(value,label) for value in block['buttons']]}
            else:
                component_count+=1;asset=assets.get(block.get('file_asset_id'))
                if not asset:error(label,'sélectionnez un fichier téléversé.')
                else:used[asset['id']]=asset
                item={'type':13,'file':{'url':f"attachment://{asset['discord_filename']}" if asset else ''},'spoiler':block['spoiler']}
            children.append(item)
        if group['boxed']:
            component_count+=1
            container={'type':17,'components':children,'spoiler':group['spoiler']}
            if group['color']:container['accent_color']=int(group['color'][1:],16)
            components.append(container)
        else:components.extend(children)
    if not components:error('Message','ajoutez du contenu.')
    if component_count>40:error('Message',f'{component_count}/40 composants : réduisez le nombre de blocs.')
    if text_count>4000:error('Message',f'{text_count}/4000 caractères de texte : raccourcissez le message.')
    mentions=doc['mentions']
    for kind in ('roles','users'):
        if any(not re.fullmatch(r'[0-9]{15,22}',value) for value in mentions[kind]):error('Mentions','identifiant Discord invalide.')
    if len(used)>10:error('Fichiers','10 fichiers au maximum par message.')
    size=sum(asset['size'] for asset in used.values())
    if size>MAX_FILES_SIZE:error('Fichiers','le total dépasse 10 Mo.')
    payload={'flags':32768 | (4096 if doc['silent'] else 0),'components':components,
             'allowed_mentions':{'parse':['everyone'] if mentions['everyone'] else [],'roles':list(dict.fromkeys(mentions['roles'])),'users':list(dict.fromkeys(mentions['users'])),'replied_user':False}}
    return {'payload':payload,'errors':errors,'component_count':component_count,'text_count':text_count,'file_size':size,'asset_ids':list(used)}
