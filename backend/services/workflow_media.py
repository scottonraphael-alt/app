"""Durable GIF uploads for welcome messages; never expose private storage paths to users."""
import asyncio
import hashlib
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import HTTPException
from database import db
from services import storage_service
from services.casework import assets,policy
from services.workflow_defaults import GIFS


async def asset_for(selector):
    if selector.startswith('iris-asset:'):
        record=await db.announcement_assets.find_one({'id':selector.split(':',1)[1],'content_type':'image/gif'})
        if not record:raise HTTPException(409,'Le GIF téléversé n’est plus disponible.')
        return record
    # Package the four owner-supplied GIFs so their expiring CDN signatures are irrelevant.
    original=next((index for index,url in enumerate(GIFS,1) if urlsplit(url).path==urlsplit(selector).path),None)
    if original:
        source=Path(__file__).resolve().parent.parent/'assets'/'welcome'/f'{original}.gif'
        if source.is_file():
            destination=f'iris/workflows/welcome/{original}.gif'
            await asyncio.to_thread(storage_service.put_object_from_file,destination,str(source),'image/gif')
            return {'storage_path':destination,'discord_filename':'welcome.gif','content_type':'image/gif','size':source.stat().st_size}
    ident=hashlib.sha256(urlsplit(selector).path.encode()).hexdigest()
    record=await db.workflow_gifs.find_one({'_id':ident})
    if not record or not await asyncio.to_thread(assets.intact,record):
        preserved=await assets.preserve({'id':ident,'filename':'welcome.gif','url':selector,'content_type':'image/gif'},
            {'id':'welcome-gifs'},'welcome',policy.Settings(max_file_bytes=10*1024*1024))
        if preserved['status']!='stored':raise HTTPException(409,'Le GIF n’est pas téléchargeable. Téléverse-le directement depuis les réglages Iris.')
        raw=storage_service._resolve_inside_root(preserved['path'])
        with raw.open('rb') as content:
            if content.read(6) not in (b'GIF87a',b'GIF89a'):raise HTTPException(422,'Le fichier doit être un GIF valide.')
        record={'_id':ident,**preserved};await db.workflow_gifs.replace_one({'_id':ident},record,upsert=True)
    return {'storage_path':record['path'],'discord_filename':'welcome.gif','content_type':'image/gif','size':record['size']}
