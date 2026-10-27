import { useState } from 'react';
import { toast } from 'sonner';
import { api,getErrorMessage } from '../../api/client';
import { Field,Modal } from './ProjectUI';
import { todayKey } from './projectUtils';

export function duplicateEnd(project,start) {
  if(!project.end_date || !start)return '';
  const span=Date.parse(`${project.end_date}T00:00:00Z`)-Date.parse(`${project.start_date}T00:00:00Z`);
  const result=new Date(Date.parse(`${start}T00:00:00Z`)+Math.max(span,0));
  return Number.isNaN(result.getTime()) || result.getUTCFullYear()>9999?'':result.toISOString().slice(0,10);
}
export default function ProjectDuplicate({project,onClose,onCreated}) {
  const [form,setForm]=useState(()=>({title:`${project.title} — copie`.slice(0,160),start_date:todayKey(),end_date:duplicateEnd(project,todayKey()),include_tasks:true}));
  const [busy,setBusy]=useState(false);
  const save=async e=>{e.preventDefault();setBusy(true);try{const r=await api.post(`/animateur/projects/${project.id}/duplicate`,{...form,title:form.title.trim(),end_date:form.end_date || null});onCreated(r.data);toast.success('La nouvelle édition du projet est prête.');}catch(error){toast.error(getErrorMessage(error));}finally{setBusy(false);}};
  return <Modal title="Une nouvelle édition" onClose={onClose} busy={busy}><form className="pj-form" onSubmit={save}><p className="pj-help">Reprenez le brief, les étiquettes et le déroulé avec de nouvelles dates. Les tâches et leurs checklists repartiront à zéro. Les membres, fichiers, rendus, commentaires, notes et bilan restent dans le projet d’origine.</p><Field label="Nom du nouveau projet" wide><input required maxLength={160} value={form.title} onChange={e=>setForm(v=>({...v,title:e.target.value}))}/></Field><Field label="Nouveau début"><input type="date" required value={form.start_date} onChange={e=>{const start=e.target.value;setForm(v=>({...v,start_date:start,end_date:v.end_date===duplicateEnd(project,v.start_date)?duplicateEnd(project,start):v.end_date}));}}/></Field><Field label="Nouvelle fin prévue"><input type="date" min={form.start_date} value={form.end_date} onChange={e=>setForm(v=>({...v,end_date:e.target.value}))}/></Field><label className="pj-check pj-wide"><input type="checkbox" checked={form.include_tasks} onChange={e=>setForm(v=>({...v,include_tasks:e.target.checked}))}/> Reprendre les tâches et leurs checklists</label><p className="pj-help">Les échéances sont décalées autour de la nouvelle fin prévue, ou du début si aucune fin n’est précisée. Les tâches vous seront attribuées et les intervenants du déroulé seront à réattribuer.</p><footer className="pj-form-actions"><button type="button" className="pj-btn" disabled={busy} onClick={onClose}>Annuler</button><button className="pj-btn pj-primary" disabled={busy || !form.title.trim()}>{busy?'Duplication…':'Dupliquer le projet'}</button></footer></form></Modal>;
}
