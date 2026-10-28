import { projectConfirm } from './projectAudit';
import { useState } from 'react';
import { toast } from 'sonner';
import { api, getErrorMessage } from '../../api/client';
import SummaryReader from '../SummaryReader';
import TiptapSummaryEditor from '../TiptapSummaryEditor';
import TaskComments from './TaskComments';
import ChecklistEditor from './ChecklistEditor';
import TaskSubtasks from './TaskSubtasks';
import { Field, Modal, Priority } from './ProjectUI';
import { dateLabel, personName, PRIORITY, TASK_STATUS, todayKey } from './projectUtils';
export function TaskForm({
  project,
  task,
  onSaved,
  onClose
}) {
  const [form, setForm] = useState({
    title: task?.title || '',
    description: task?.description || '',
    assignee_id: task?.assignee?.id || project.members[0]?.id || '',
    due_date: task?.due_date || project.end_date || todayKey(),
    priority: task?.priority || 'normale',
    checklist: (task?.checklist || []).map(item=>({...item}))
  });
  const [busy, setBusy] = useState(false);
  const change = key => e => setForm(v => ({
    ...v,
    [key]: e.target.value
  }));
  const submit = async e => {
    e.preventDefault();
    setBusy(true);
    try {
      const response = task ? await api.patch(`/animateur/tasks/${task.id}`, {...form,expected_updated_at:task.updated_at}) : await api.post(`/animateur/projects/${project.id}/tasks`, form);
      onSaved(response.data);
      toast.success(task ? 'Tâche mise à jour.' : 'Tâche ajoutée.');
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setBusy(false);
    }
  };
  return <Modal title={task ? 'Ajuster la tâche' : 'Une nouvelle étape'} onClose={onClose} busy={busy}><form className="pj-form" onSubmit={submit}><p className="pj-help">Décrivez le résultat attendu, puis choisissez la personne qui s’en charge.</p><Field label="Nom de la tâche" wide><input required maxLength={160} value={form.title} onChange={change('title')} /></Field><Field label="Consignes et résultat attendu" wide><textarea rows={4} maxLength={4000} value={form.description} onChange={change('description')} /></Field><Field label="Attribuer à"><select required value={form.assignee_id} onChange={change('assignee_id')}><option value="">Choisir un membre</option>{project.members.map(m => <option key={m.id} value={m.id}>{personName(m)}</option>)}</select></Field><Field label="Échéance"><input required type="date" value={form.due_date} onChange={change('due_date')} /></Field><Field label="Priorité"><select value={form.priority} onChange={change('priority')}>{Object.entries(PRIORITY).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field><ChecklistEditor value={form.checklist} onChange={checklist=>setForm(v=>({...v,checklist}))}/><footer className="pj-form-actions"><button type="button" className="pj-btn" onClick={onClose} disabled={busy}>Annuler</button><button className="pj-btn pj-primary" disabled={busy || !form.title.trim()}>{busy ? 'Enregistrement…' : task ? 'Enregistrer' : 'Ajouter la tâche'}</button></footer></form></Modal>;
}
export default function ProjectTaskDialog({
  task,
  helper,
  manager,
  writable,
  onSaved,
  onDelete,
  onEdit,
  onClose,
  members = []
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(task.submission_note || '');
  const [file, setFile] = useState(null);
  const [block, setBlock] = useState(task.blocked_reason || '');
  const [review, setReview] = useState('');
  const [reopenAssignee, setReopenAssignee] = useState(members.some(m => m.id === task.assignee?.id) ? task.assignee.id : members[0]?.id || '');
  const [submitting, setSubmitting] = useState(false);
  const own = task.assignee?.id === helper?.id;
  const working = ['a_faire', 'en_cours'].includes(task.status);
  const checklist = task.checklist || [];
  const checklistDone = checklist.filter(item=>item.done).length;
  const act = async operation => {
    setBusy(true);
    try {
      const response = await operation();
      if (response?.data) onSaved(response.data);
      toast.success('Tâche mise à jour.');
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setBusy(false);
    }
  };
  const patch = body => act(() => api.patch(`/animateur/tasks/${task.id}`, body));
  const submit = () => act(async () => {
    const body = new FormData();
    body.append('submission_content', note);
    if (file) body.append('file', file);
    const response = await api.put(`/animateur/tasks/${task.id}/submit`, body);
    setSubmitting(false);
    return response;
  });
  return <Modal title={task.title} onClose={onClose} busy={busy}><div className="pj-task-detail"><div className="pj-inline"><span className={`pj-badge pj-task-${task.status}`}>{TASK_STATUS[task.status]}</span><Priority value={task.priority} /></div><p className="pj-help">{personName(task.assignee)} · échéance le {dateLabel(task.due_date, true)}</p><p className="pj-preline">{task.description || 'Aucune consigne complémentaire.'}</p>{task.blocked_reason && <div className="pj-notice"><strong>Un coup de main est nécessaire</strong><p>{task.blocked_reason}</p></div>}{task.review_note && <div className="pj-review"><strong>Consigne de correction</strong><p>{task.review_note}</p></div>}
    {!!checklist.length && <fieldset className="pj-checklist" disabled={busy || !writable || !working || (!own && !manager)}><legend>Les étapes <span>{checklistDone}/{checklist.length}</span></legend><div>{checklist.map(item=><label key={item.id} className={item.done?'is-done':''}><input type="checkbox" checked={!!item.done} onChange={e=>act(()=>api.patch(`/animateur/tasks/${task.id}/checklist/${item.id}`,{done:e.target.checked,expected_updated_at:task.updated_at}))}/><span>{item.title}</span></label>)}</div></fieldset>}
    {(!!checklist.length || (writable && working && (own || manager))) && <TaskSubtasks task={task} canEdit={writable && working && (own || manager)} onChanged={onSaved} />}
    {task.submission_note && !submitting && <section className="pj-submission"><h3>Le rendu</h3><SummaryReader key={task.updated_at} content={task.submission_note} /></section>}{task.submission_file && <a className="pj-btn" href={`${api.defaults.baseURL}/animateur/tasks/${task.id}/submission/download`}>Télécharger · {task.submission_file.original_filename}</a>}
    {writable && working && (own || manager) && <><div className="pj-inline">{task.status === 'a_faire' ? <button className="pj-btn pj-primary" disabled={busy} onClick={() => patch({
            status: 'en_cours'
          })}>Commencer la tâche</button> : <button className="pj-btn" disabled={busy} onClick={() => patch({
            status: 'a_faire'
          })}>Remettre à faire</button>}{own && <button className="pj-btn pj-primary" disabled={busy} onClick={() => setSubmitting(v => !v)}>{submitting ? 'Masquer le formulaire' : 'Préparer mon rendu'}</button>}</div><details className="pj-block-form"><summary>Signaler ou lever un blocage</summary><Field label="Ce qui vous empêche d’avancer"><textarea rows={2} maxLength={1000} value={block} onChange={e => setBlock(e.target.value)} placeholder="Besoin d’une décision, d’un accès… Effacez le texte pour lever le blocage." /></Field><button className="pj-btn" disabled={busy} onClick={() => patch({
            blocked_reason: block.trim()
          })}>Enregistrer le blocage</button></details></>}
    {submitting && writable && own && working && <section className="pj-submission"><h3>Présenter mon travail</h3><p className="pj-help">Expliquez le résultat et ajoutez un fichier si nécessaire.</p><TiptapSummaryEditor value={note} onChange={setNote} placeholder="Le résultat, les liens utiles…" /><Field label="Pièce jointe · facultatif"><input type="file" onChange={e => setFile(e.target.files?.[0] || null)} /></Field><p className="pj-help">{checklistDone<checklist.length?'Terminez les étapes de la checklist avant d’envoyer le rendu.':'Le rendu sera relu par le pilote du projet.'}</p><button className="pj-btn pj-primary" onClick={submit} disabled={busy || checklistDone<checklist.length}>{busy ? 'Envoi…' : 'Envoyer pour validation'}</button></section>}
    {manager && writable && !working && <section className="pj-review"><h3>{task.status === 'rendu' ? 'Le travail est prêt à être relu.' : 'Cette tâche est validée.'}</h3>{task.status === 'rendu' && <button className="pj-btn pj-primary" disabled={busy} onClick={() => act(() => api.put(`/animateur/tasks/${task.id}/validate`))}>Valider le rendu</button>}<Field label="Responsable de la correction"><select value={reopenAssignee} onChange={e => setReopenAssignee(e.target.value)}>{members.map(m => <option key={m.id} value={m.id}>{personName(m)}</option>)}</select></Field><Field label="Demander une correction ou rouvrir la tâche"><textarea value={review} rows={2} maxLength={2000} onChange={e => setReview(e.target.value)} placeholder="Précisez ce qu’il reste à faire…" /></Field><button className="pj-btn" disabled={busy || !review.trim() || !reopenAssignee} onClick={() => patch({
          status: 'en_cours',
          review_note: review.trim(),
          assignee_id: reopenAssignee
        })}>Renvoyer en cours</button></section>}
    {(manager || members.some(member=>member.id===helper?.id)) && <TaskComments key={task.id} taskId={task.id} helper={helper} manager={manager} writable={writable}/>}
    {manager && writable && <footer className="pj-form-actions">{working && <button className="pj-btn" disabled={busy} onClick={onEdit}>Modifier la tâche</button>}<button className="pj-btn pj-danger" disabled={busy} onClick={() => {
          if (projectConfirm('Supprimer définitivement cette tâche et son rendu ?')) act(async () => {
            await api.delete(`/animateur/tasks/${task.id}`);
            onDelete(task.id);
          });
        }}>Supprimer la tâche</button></footer>}</div></Modal>;
}
