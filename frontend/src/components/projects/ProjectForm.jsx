import { useState } from 'react';
import { api, getErrorMessage } from '../../api/client';
import { toast } from 'sonner';
import { Field, Modal } from './ProjectUI';
import { PRIORITY, todayKey } from './projectUtils';
export default function ProjectForm({
  project,
  onClose,
  onSaved
}) {
  const [form, setForm] = useState({
    title: project?.title || '',
    description: project?.description || '',
    start_date: project?.start_date || todayKey(),
    end_date: project?.end_date || '',
    priority: project?.priority || 'normale',
    tags: (project?.tags || []).join(', ')
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
      const payload = {
        ...form,
        title: form.title.trim(),
        end_date: form.end_date || null,
        tags: [...new Set(form.tags.split(',').map(t => t.trim()).filter(Boolean))]
      };
      const response = project ? await api.patch(`/animateur/projects/${project.id}/settings`, payload) : await api.post('/animateur/projects', payload);
      onSaved(response.data);
      toast.success(project ? 'Projet mis à jour.' : 'Le projet est prêt !');
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setBusy(false);
    }
  };
  return <Modal title={project ? 'Paramètres du projet' : 'Une nouvelle idée ?'} busy={busy} onClose={onClose}><form onSubmit={submit} className="pj-form"><p className="pj-help">Posez le cadre. Vous pourrez ensuite construire le brief et répartir les tâches avec l’équipe.</p><Field label="Nom du projet" wide><input required maxLength={160} value={form.title} onChange={change('title')} placeholder="Ex. Soirée jeux d’automne" /></Field><Field label="L’idée en quelques mots" wide><textarea rows={3} maxLength={4000} value={form.description} onChange={change('description')} placeholder="Quel moment souhaitez-vous créer, et pour qui ?" /></Field><Field label="Début"><input type="date" required value={form.start_date} onChange={change('start_date')} /></Field><Field label="Fin prévue · facultatif"><input type="date" min={form.start_date} value={form.end_date} onChange={change('end_date')} /></Field><Field label="Priorité"><select value={form.priority} onChange={change('priority')}>{Object.entries(PRIORITY).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field><Field label="Étiquettes · jusqu’à 8"><input maxLength={260} value={form.tags} onChange={change('tags')} placeholder="Jeux, vocal, communauté…" /></Field><footer className="pj-form-actions"><button type="button" className="pj-btn" onClick={onClose} disabled={busy}>Annuler</button><button className="pj-btn pj-primary" disabled={busy || !form.title.trim()}>{busy ? 'Enregistrement…' : project ? 'Enregistrer' : 'Créer le projet'}</button></footer></form></Modal>;
}
