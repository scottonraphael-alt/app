"""User-owned dashboard preferences. Widget availability follows the current role flags."""
WIDGETS = {
 'day': ('Ma journée', 8), 'team': ('Équipe en ligne', 4),
 'next-actions': ('À traiter maintenant', 12),
 'casework': ('Dossiers des membres', 12), 'music': ('Karaoké & blind test', 12),
 'responsable': ('Outils responsable', 12), 'shortcuts': ('Accès principaux', 12),
 'quarterly': ('Engagements trimestriels', 12), 'helper': ('Mon espace helper', 12),
 'animateur': ('Mon espace animateur', 12),
}

def available_widgets(flags):
 staff=any(flags.get('is_'+r) for r in ('staff','responsable','admin','helper','operateur'))
 allow={'music'}
 if staff: allow.update(('day','team','shortcuts','quarterly'))
 if staff or flags.get('is_server_admin'): allow.add('next-actions')
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
 for widget in available:
  if widget['id'] in seen: continue
  config = {'id': widget['id'], 'width': widget['width'], 'hidden': False, 'collapsed': False}
  if widget['id'] == 'next-actions':
   result.insert(2, config)
  else:
   result.append(config)
 return {'version':1,'widgets':result,'available':available}
