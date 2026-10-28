import { useState } from 'react';
import { Plus } from 'lucide-react';
import { toast } from 'sonner';
import { api, getErrorMessage } from '../../api/client';

export function ProgressBar({ done, total, label = 'Progression' }) {
  const percent = total ? Math.round(done * 100 / total) : 0;
  return <div className="pj-progress-line"><div className="pj-progress-bar" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}><span style={{ width: `${percent}%` }} /></div><small>{done}/{total} · {percent} %</small></div>;
}

export default function TaskSubtasks({ task, canEdit, onChanged }) {
  const [title, setTitle] = useState('');
  const [busy, setBusy] = useState(false);
  const items = task.checklist || [];
  const done = items.filter(item => item.done).length;
  const add = async e => {
    e.preventDefault();
    if (!title.trim()) return;
    setBusy(true);
    try {
      const r = await api.post(`/project-extras/tasks/${task.id}/subtasks`, { title: title.trim() });
      onChanged({ ...task, checklist: r.data.items, updated_at: r.data.updated_at });
      setTitle('');
    } catch (error) { toast.error(getErrorMessage(error)); } finally { setBusy(false); }
  };
  return <div className="pj-subtasks">
    {!!items.length && <ProgressBar done={done} total={items.length} label="Progression des sous-tâches" />}
    {canEdit && items.length < 50 && <form className="pj-checklist-add" onSubmit={add}><input aria-label="Nouvelle sous-tâche" maxLength={160} value={title} disabled={busy} onChange={e => setTitle(e.target.value)} placeholder="Ajouter une sous-tâche…" /><button className="pj-btn" disabled={busy || !title.trim()}><Plus size={15} /> Ajouter</button></form>}
  </div>;
}
