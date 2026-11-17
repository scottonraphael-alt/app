"""User-owned dashboard preferences. Widget availability follows the current role flags."""
WIDGETS = {
 'day': ('Ma journée', 8), 'team': ('Équipe en ligne', 4),
 'casework': ('Dossiers des membres', 12), 'music': ('Karaoké & blind test', 12),
 'responsable': ('Outils responsable', 12), 'shortcuts': ('Accès principaux', 12),
 'quarterly': ('Engagements trimestriels', 12), 'helper': ('Mon espace helper', 12),
 'animateur': ('Mon espace animateur', 12),
}

def available_widgets(flags):
 staff=any(flags.get('is_'+r) for r in ('staff','responsable','admin','helper','operateur'))
 allow={'music'}
 if staff: allow.update(('day','team','shortcuts','quarterly'))
 if any(flags.get('is_'+r) for r in ('staff','responsable','server_admin')): allow.add('casework')
 if flags.get('is_responsable'): allow.add('responsable')
 if flags.get('is_helper') or flags.get('is_admin'): allow.add('helper')
 if flags.get('is_animateur') or flags.get('is_responsable'): allow.add('animateur')
 return [{'id':key,'label':label,'width':width} for key,(label,width) in WIDGETS.items() if key in allow]

def layout_payload(available, stored):
 known={w['id']:w for w in available}
 result=[];seen=set()
 for item in stored if isinstance(stored,list) else []:
  if not isinstance(item,dict) or item.get('id') not in known or item['id'] in seen: continue
  seen.add(item['id']);result.append({'id':item['id'],'width':item.get('width') if item.get('width') in (4,6,8,12) else known[item['id']]['width'],'hidden':item.get('hidden') is True,'collapsed':item.get('collapsed') is True})
 result.extend({'id':w['id'],'width':w['width'],'hidden':False,'collapsed':False} for w in available if w['id'] not in seen)
 return {'version':1,'widgets':result,'available':available}
