import { useEffect, useState } from 'react';
import { ArrowDown, ArrowUp, Download, Pencil, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { api, getErrorMessage } from '../../api/client';
import { Empty, Field, Panel, Pagination, usePage } from './ProjectUI';
import { dateLabel, personName } from './projectUtils';
import { durationLabel, durationParts, durationMinutes, rundownPoint, rundownText, rundownTimeline } from './rundownUtils';

const step=(title='',minutes=15)=>({id:globalThis.crypto?.randomUUID?.() || `seq-${Date.now()}-${Math.random().toString(36).slice(2)}`,title,duration_minutes:minutes,...durationParts(minutes),speaker_id:'',notes:''});
const initial=project=>({event_date:project.rundown?.event_date || project.start_date || project.end_date || '',start_time:project.rundown?.start_time || '20:00',items:(project.rundown?.items || []).map(item=>({id:item.id,title:item.title,duration_minutes:item.duration_minutes,...durationParts(item.duration_minutes),speaker_id:item.speaker?.id || '',notes:item.notes || ''}))});
export default function ProjectRundown({project,manager,onSaved}) {
  const [draft,setDraft]=useState(()=>initial(project));
  const [editing,setEditing]=useState(false);
  const [busy,setBusy]=useState(false);
  const [conflict,setConflict]=useState(false);
  const plan=project.rundown;
  const writable=manager && project.status==='en_cours';
  useEffect(()=>{setDraft(initial(project));setEditing(false);setConflict(false);},[project.id,plan?.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps
  const timeline=rundownTimeline(editing?draft.start_time:plan?.start_time,editing?draft.items:plan?.items || [],editing?draft.event_date:plan?.event_date);
  const total=timeline.reduce((sum,item)=>sum+(Number(item.duration_minutes)||0),0);
  const invalidDuration=draft.items.some(item=>!Number.isSafeInteger(item.duration_minutes) || item.duration_minutes<1 || item.duration_minutes>2147483647);
  const pages=usePage(timeline,8,plan?.updated_at);
  const change=key=>e=>setDraft(v=>({...v,[key]:e.target.value}));
  const update=(id,key,value)=>setDraft(v=>({...v,items:v.items.map(item=>item.id===id?{...item,[key]:value}:item)}));
  const updateDuration=(id,key,value)=>setDraft(v=>({...v,items:v.items.map(item=>{if(item.id!==id)return item;const next={...item,[key]:value};return {...next,duration_minutes:durationMinutes(next)};})}));
  const move=(index,delta)=>setDraft(v=>{const items=[...v.items];[items[index],items[index+delta]]=[items[index+delta],items[index]];return {...v,items};});
  const save=async e=>{
    e.preventDefault();setBusy(true);setConflict(false);
    try {const r=await api.put(`/animateur/projects/${project.id}/rundown`,{...draft,event_date:draft.event_date || null,items:draft.items.map(({duration_days,duration_hours,duration_remainder,...item})=>({...item,duration_minutes:Number(item.duration_minutes),speaker_id:item.speaker_id || null})),expected_updated_at:plan?.updated_at || null});onSaved(r.data);setEditing(false);toast.success('Déroulé enregistré.');}
    catch(error){setConflict(error.response?.status===409);toast.error(getErrorMessage(error));}finally{setBusy(false);}
  };
  const reload=async()=>{setBusy(true);try{const r=await api.get(`/animateur/projects/${project.id}`);onSaved(r.data);setDraft(initial(r.data));setEditing(false);setConflict(false);}catch(error){toast.error(getErrorMessage(error));}finally{setBusy(false);}};
  const exportText=()=>{const url=URL.createObjectURL(new Blob([rundownText(project)],{type:'text/plain;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download=`deroule-${project.id}.txt`;link.click();URL.revokeObjectURL(url);};
  return <Panel title="Le fil de l’animation" intro="Préparez les séquences, leur durée en jours, heures et minutes, et qui intervient. Les horaires s’enchaînent automatiquement à partir de l’heure de départ, en heure de Paris." className="pj-rundown" actions={!editing && <div className="pj-inline">{!!plan?.items?.length && <button className="pj-btn" onClick={exportText}><Download size={15}/> Exporter le déroulé</button>}{writable && <button className="pj-btn" onClick={()=>setEditing(true)}><Pencil size={15}/>{plan?.items?.length?'Modifier le déroulé':'Préparer le déroulé'}</button>}</div>}>
    {(timeline.length>0 || editing) && <div className="pj-rundown-summary"><span>{(editing?draft.event_date:plan?.event_date)?dateLabel(editing?draft.event_date:plan?.event_date,true):'Date à préciser'}</span><span><strong>{timeline.length}</strong> séquence{timeline.length>1?'s':''}</span><span><strong>{durationLabel(total)}</strong> au total</span>{!!timeline.length && <span>{rundownPoint(timeline[0],'start')} → {rundownPoint(timeline[timeline.length-1],'end')}</span>}</div>}
    {editing && writable ? <form className="pj-rundown-form" onSubmit={save}>
      <div className="pj-rundown-fields"><Field label="Date de début de l’animation"><input type="date" value={draft.event_date} onChange={change('event_date')}/></Field><Field label="Heure de départ · Paris"><input type="time" required value={draft.start_time} onChange={change('start_time')}/></Field></div>
      <div className="pj-rundown-editor">{draft.items.map((item,index)=><section key={item.id} className="pj-sequence-edit"><header><strong>Séquence {index+1} · {rundownPoint(timeline[index],'start')} → {rundownPoint(timeline[index],'end')}</strong><div className="pj-inline"><button type="button" className="pj-icon" aria-label={`Monter la séquence ${index+1}`} disabled={busy || index===0} onClick={()=>move(index,-1)}><ArrowUp size={15}/></button><button type="button" className="pj-icon" aria-label={`Descendre la séquence ${index+1}`} disabled={busy || index===draft.items.length-1} onClick={()=>move(index,1)}><ArrowDown size={15}/></button><button type="button" className="pj-icon pj-danger" aria-label={`Retirer la séquence ${index+1}`} disabled={busy} onClick={()=>setDraft(v=>({...v,items:v.items.filter(i=>i.id!==item.id)}))}><Trash2 size={15}/></button></div></header>
        <div className="pj-sequence-fields"><Field label="Nom de la séquence"><input required maxLength={160} aria-label={`Nom de la séquence ${index+1}`} value={item.title} onChange={e=>update(item.id,'title',e.target.value)}/></Field><fieldset className="pj-sequence-duration"><legend>Durée</legend><div>{[['duration_days','Jours',null],['duration_hours','Heures',23],['duration_remainder','Minutes',59]].map(([key,label,max])=><Field key={key} label={label}><input type="number" required min="0" max={max || undefined} step="1" aria-label={`${label} de la séquence ${index+1}`} value={item[key]} onChange={e=>updateDuration(item.id,key,e.target.value)}/></Field>)}</div></fieldset><Field label="Intervenant"><select aria-label={`Intervenant de la séquence ${index+1}`} value={item.speaker_id} onChange={e=>update(item.id,'speaker_id',e.target.value)}><option value="">À attribuer</option>{project.members.map(member=><option key={member.id} value={member.id}>{personName(member)}</option>)}</select></Field></div>
        <details className="pj-sequence-notes"><summary>Consignes et matériel</summary><Field label="Notes pour cette séquence"><textarea maxLength={1500} rows={2} aria-label={`Consignes de la séquence ${index+1}`} value={item.notes} onChange={e=>update(item.id,'notes',e.target.value)} placeholder="Les transitions, les supports, les points à garder en tête…"/></Field></details>
      </section>)}</div>
      {!draft.items.length && <Empty title="Quel sera le premier temps de l’animation ?">Ajoutez vos séquences ou partez d’une trame accueil, animation et clôture.</Empty>}
      <div className="pj-inline"><button type="button" className="pj-btn" disabled={busy || draft.items.length>=50} onClick={()=>setDraft(v=>({...v,items:[...v.items,step()]}))}><Plus size={15}/> Ajouter une séquence</button>{!draft.items.length && <button type="button" className="pj-btn" disabled={busy} onClick={()=>setDraft(v=>({...v,items:[step('Accueil',10),step('Animation',40),step('Clôture',10)]}))}>Utiliser une trame simple</button>}<span className="pj-help">{draft.items.length}/50 séquences · une séquence peut s’étendre sur plusieurs jours</span></div>
      {invalidDuration && <p className="pj-notice" role="alert">Chaque séquence doit durer au moins une minute et avoir une durée entière valide.</p>}
      {conflict && <div className="pj-notice"><p>Le déroulé ou l’équipe a changé. Copiez vos modifications avant de recharger la version enregistrée.</p><button type="button" className="pj-btn" disabled={busy} onClick={reload}>Recharger le déroulé</button></div>}
      <footer className="pj-form-actions"><button type="button" className="pj-btn" disabled={busy} onClick={()=>{setDraft(initial(project));setEditing(false);}}>Annuler</button><button className="pj-btn pj-primary" disabled={busy || invalidDuration}>{busy?'Enregistrement…':'Enregistrer le déroulé'}</button></footer>
    </form> : !timeline.length ? <Empty title="Une animation, plusieurs temps forts.">Le déroulé rassemble les horaires, les personnes qui interviennent et les consignes pour le jour J.</Empty> : <>
      <ol className="pj-rundown-timeline" start={(pages.page-1)*8+1}>{pages.items.map((item,index)=><li key={item.id}><div className="pj-sequence-time"><span className="pj-sequence-date">{item.startDate?dateLabel(item.startDate):item.start.includes('J+')?item.start.split(' · ')[1]:'Début'}</span><strong>{item.startClock}</strong><span className="pj-sequence-end">→ {item.endDate?`${dateLabel(item.endDate)} · ${item.endClock}`:item.end}</span><small>{durationLabel(item.duration_minutes)}</small></div><div className="pj-sequence-copy"><h3><span>{(pages.page-1)*8+index+1}.</span> {item.title}</h3><p>{item.speaker?personName(item.speaker):'Intervenant à attribuer'}</p>{item.notes && <details><summary>Consignes et matériel</summary><p>{item.notes}</p></details>}</div></li>)}</ol>
      <Pagination page={pages.page} pageSize={8} total={timeline.length} onChange={pages.setPage} label="séquences du déroulé"/>
      <p className="pj-help">Mis à jour par {personName(plan.updated_by)} · {new Date(plan.updated_at).toLocaleString('fr-FR',{timeZone:'Europe/Paris',dateStyle:'medium',timeStyle:'short'})}. Les jours suivent le calendrier en heure de Paris. Sans date précisée, J+N indique le décalage depuis le début.</p>
    </>}
  </Panel>;
}
