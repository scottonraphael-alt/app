"""Persistent personal best per song; overall rank sums those bests only."""
import hashlib
import time
from database import db


async def record(track, rows):
    if not track:
        return
    for row in rows:
        points = row.get('points', 0)
        if not isinstance(points, int) or points <= 0:
            continue
        uid = str(row['id'])
        key = hashlib.sha256((track.id+':'+uid).encode()).hexdigest()
        await db.karaoke_bests.update_one({'_id':key}, {'$max': {'points':points}, '$set': {
            'user_id':uid, 'track_id':track.id, 'name':row['name'], 'title':track.title,
            'artist':track.artist, 'updated_at':time.time()}}, upsert=True)


async def leaderboard(track_id=None):
    if track_id:
        rows = await db.karaoke_bests.find({'track_id':track_id}, {'_id':0}).sort([('points',-1),('user_id',1)]).limit(100).to_list(100)
        return [{'rank':i+1,'id':r['user_id'],'name':r['name'],'points':r['points'],'songs':1} for i,r in enumerate(rows)]
    rows = await db.karaoke_bests.aggregate([
        {'$group':{'_id':'$user_id','name':{'$last':'$name'},'points':{'$sum':'$points'},'songs':{'$sum':1}}},
        {'$sort':{'points':-1,'_id':1}}, {'$limit':100}
    ]).to_list(100)
    return [{'rank':i+1,'id':r['_id'],'name':r['name'],'points':r['points'],'songs':r['songs']} for i,r in enumerate(rows)]
