import { useEffect, useState } from 'react';
import { Pencil } from 'lucide-react';
import { toast } from 'sonner';
import { api, getErrorMessage } from '../../api/client';
import { Empty, Field, Panel } from './ProjectUI';
import { dateLabel, personName } from './projectUtils';

const initial=project=>({attendance:project.review?.attendance ?? '',event_date:project.review?.event_date || project.end_date || '',successes:project.review?.successes || '',improvements:project.review?.improvements || '',next_steps:project.review?.next_steps || ''});
export default function ProjectReview({project,manager,onSaved}) {
  const [form,setForm]=useState(()=>initial(project));
  const [editing,setEditing]=useState(false);
  const [busy,setBusy]=useState(false);
  const [conflict,setConflict]=useState(false);
  const review=project.review;
  const writable=manager && project.status!=='archive';
  useEffect(()=>{setForm(initial(project));setEditing(false);setConflict(false);},[project.id,project.review?.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps
  const change=key=>e=>setForm(v=>({...v,[key]:e.target.value}));
  const save=async e=>{
    e.preventDefault();setBusy(true);setConflict(false);
    try {const r=await api.put(`/animateur/projects/${project.id}/review`,{...form,attendance:form.attendance===''?null:Number(form.attendance),event_date:form.event_date || null,expected_updated_at:review?.updated_at || null});onSaved(r.data);setEditing(false);toast.success('Bilan enregistré.');}
    catch(error){setConflict(error.response?.status===409);toast.error(getErrorMessage(error));}finally{setBusy(false);}
  };
  const reload=async()=>{setBusy(true);try{const r=await api.get(`/animateur/projects/${project.id}`);onSaved(r.data);setForm(initial(r.data));setEditing(false);setConflict(false);}catch(error){toast.error(getErrorMessage(error));}finally{setBusy(false);}};
  return <Panel title="Ce qu’on retient de l’animation" intro="La participation, les réussites et les idées à garder pour la prochaine fois. Le pilote peut compléter ce bilan même après la clôture." className="pj-event-review" actions={writable && !editing && <button className="pj-btn" onClick={()=>setEditing(true)}><Pencil size={15}/>{review?'Modifier le bilan':'Rédiger le bilan'}</button>}>
    {editing && writable ? <form className="pj-review-form" onSubmit={save}>
      <Field label="Date de l’animation"><input type="date" value={form.event_date} onChange={change('event_date')}/></Field><Field label="Nombre de participants · facultatif"><input type="number" min="0" max="1000000" step="1" value={form.attendance} onChange={change('attendance')} placeholder="Non renseigné"/></Field>
      <Field label="Ce qui a bien fonctionné" wide><textarea rows={3} maxLength={4000} value={form.successes} onChange={change('successes')} placeholder="Les moments forts, les retours positifs…"/></Field>
      <Field label="Ce qu’on peut améliorer" wide><textarea rows={3} maxLength={4000} value={form.improvements} onChange={change('improvements')} placeholder="Les difficultés et les ajustements utiles…"/></Field>
      <Field label="À garder pour la prochaine fois" wide><textarea rows={3} maxLength={4000} value={form.next_steps} onChange={change('next_steps')} placeholder="Les idées ou décisions à reprendre…"/></Field>
      {conflict && <div className="pj-notice pj-wide"><p>Le bilan a changé entre-temps. Copiez vos modifications avant de recharger la version enregistrée.</p><button type="button" className="pj-btn" disabled={busy} onClick={reload}>Recharger le bilan</button></div>}
      <footer className="pj-form-actions"><button type="button" className="pj-btn" disabled={busy} onClick={()=>{setForm(initial(project));setEditing(false);}}>Annuler</button><button className="pj-btn pj-primary" disabled={busy}>{busy?'Enregistrement…':'Enregistrer le bilan'}</button></footer>
    </form> : !review ? <Empty title="Une animation, des enseignements.">Après l’événement, gardez une trace de ce qui a fonctionné et de ce que vous souhaitez faire évoluer.</Empty> : <>
      <div className="pj-review-facts"><span>{review.attendance==null?'Participation non renseignée':<><strong>{review.attendance}</strong> participants</>}</span><span>{review.event_date?dateLabel(review.event_date,true):'Date non renseignée'}</span></div>
      <div className="pj-review-sections">{[['successes','Les réussites'],['improvements','Les pistes d’amélioration'],['next_steps','Pour la prochaine fois']].map(([key,label])=><section key={key}><h3>{label}</h3><p>{review[key] || 'Pas encore renseigné.'}</p></section>)}</div>
      <p className="pj-help">Dernière mise à jour par {personName(review.updated_by)} · {new Date(review.updated_at).toLocaleString('fr-FR',{timeZone:'Europe/Paris',dateStyle:'medium',timeStyle:'short'})}</p>
    </>}
  </Panel>;
}
