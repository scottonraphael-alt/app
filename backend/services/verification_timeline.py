"""Prepared source for member_360. Call only after checking Staff permission."""
from database import db
from services import verification_service as service

LABELS={'form.submitted':'Formulaire envoyé','form.imported':'Formulaire historique importé',
        'action.claim':'Vérification prise en charge','action.confirmed':'Décision de vérification confirmée',
        'action.second_opinion':'Second avis demandé','effect.unconfirmed':'Action de vérification à terminer'}

async def entries(member_id,*,can_verifications):
    if not can_verifications:return None  # No read, count or existence leak.
    row=await db.verification_cases.find_one({'_id':service.key(member_id),'guild_id':service.guild()},
        {'events':1,'forms.id':1,'forms.submitted_at':1,'forms.status':1,'status':1,'training':1})
    if not row or not row.get('forms'):return {'entries':[],'count':0,'first_form_at':None}
    events=[{'type':'verification','id':event['id'],'at':event['at'],'title':LABELS.get(event['kind'],'Vérification'),
             'detail':event.get('action',''),'url':f'/staff/verifications/{member_id}','severity':'info'}
            for event in row.get('events',[]) if event.get('form_id') and event['kind'] in LABELS]
    return {'entries':events,'count':len(row['forms']),'status':row['status'],
            'first_form_at':min((form['submitted_at'] for form in row['forms'] if form.get('submitted_at')),default=None),'training':row['training']}
