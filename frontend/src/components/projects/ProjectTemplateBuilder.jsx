import { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { api, getErrorMessage } from '../../api/client';
import { Field, Modal } from './ProjectUI';

const blank = () => ({ key: Math.random().toString(36).slice(2), title: '', offset_days: 0, checklist: '' });

export default function ProjectTemplateBuilder({ onClose, onSaved }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [tasks, setTasks] = useState([blank()]);
  const [busy, setBusy] = useState(false);
  const set = (key, patch) => setTasks(v => v.map(t => t.key === key ? { ...t, ...patch } : t));
  const submit = async e => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post('/project-extras/templates', {
        name: name.trim(), description: description.trim(),
        tasks: tasks.filter(t => t.title.trim()).map(t => ({ title: t.title.trim(), offset_days: Number(t.offset_days) || 0, checklist: t.checklist.split('\n').map(s => s.trim()).filter(Boolean) })),
      });
      toast.success('Modèle créé.');
      onSaved?.();
      onClose();
    } catch (error) { toast.error(getErrorMessage(error)); } finally { setBusy(false); }
  };
  return <Modal title="Nouveau modèle de projet" busy={busy} onClose={onClose}><form className="pj-form" onSubmit={submit}>
    <p className="pj-help">Les échéances sont relatives à la fin du projet : -7 signifie sept jours avant, 0 le jour même.</p>
    <Field label="Nom du modèle" wide><input required maxLength={100} value={name} onChange={e => setName(e.target.value)} /></Field>
    <Field label="Description" wide><textarea rows={2} maxLength={2000} value={description} onChange={e => setDescription(e.target.value)} /></Field>
    <div className="pj-wide pj-tpl-tasks">{tasks.map((t, i) => <fieldset key={t.key}><legend>Tâche {i + 1}</legend>
      <Field label="Titre"><input maxLength={160} value={t.title} onChange={e => set(t.key, { title: e.target.value })} /></Field>
      <Field label="Décalage (jours)"><input type="number" min={-365} max={365} value={t.offset_days} onChange={e => set(t.key, { offset_days: e.target.value })} /></Field>
      <Field label="Sous-tâches (une par ligne)" wide><textarea rows={2} value={t.checklist} onChange={e => set(t.key, { checklist: e.target.value })} /></Field>
      {tasks.length > 1 && <button type="button" className="pj-icon pj-danger" aria-label={`Retirer la tâche ${i + 1}`} onClick={() => setTasks(v => v.filter(x => x.key !== t.key))}><Trash2 size={15} /></button>}
    </fieldset>)}
    {tasks.length < 50 && <button type="button" className="pj-btn" onClick={() => setTasks(v => [...v, blank()])}><Plus size={15} /> Ajouter une tâche</button>}</div>
    <div className="pj-form-actions"><button type="button" className="pj-btn" disabled={busy} onClick={onClose}>Annuler</button><button className="pj-btn pj-primary" disabled={busy || !name.trim() || !tasks.some(t => t.title.trim())}>Créer le modèle</button></div>
  </form></Modal>;
}
