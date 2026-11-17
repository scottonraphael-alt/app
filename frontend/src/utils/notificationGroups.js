export const isUrgentNotification=item=>['ticket_crisis','handoff_urgent'].includes(item.type)||item.priority==='urgent'||item.urgent===true;
// Group only the loaded notifications, by exact destination and UTC day. Urgencies remain individual.
export function groupNotifications(items=[]){
 const groups=[],byKey=new Map();
 for(const item of items){const date=String(item.created_at||'').slice(0,10),link=typeof item.link==='string'&&item.link.startsWith('/')?item.link:null;
  const key=link&&/^\d{4}-\d{2}-\d{2}$/.test(date)&&!isUrgentNotification(item)?`${date}:${link}`:`individual:${item.id}`;
  let group=byKey.get(key);if(!group){group={key,items:[]};byKey.set(key,group);groups.push(group);}group.items.push(item);
 }
 return groups.map(group=>({...group,latest:group.items.reduce((a,b)=>String(b.created_at)>String(a.created_at)?b:a),unread:group.items.filter(n=>!n.read_at).length}));
}
