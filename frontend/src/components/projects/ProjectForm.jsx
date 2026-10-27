import { useEffect, useState } from 'react';
import { api, getErrorMessage } from '../../api/client';
import { toast } from 'sonner';
import { Field, Modal } from './ProjectUI';
import { projectConfirm } from './projectAudit';
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
  const [templates,setTemplates]=useState([]);
  const [templateId,setTemplateId]=useState('');
  const [templateError,setTemplateError]=useState(false);
  const [templateLoading,setTemplateLoading]=useState(false);
  const loadTemplates=async()=>{setTemplateLoading(true);setTemplateError(false);try{const r=await api.get('/animateur/projects/workspace/templates');if(!Array.isArray(r.data))throw new Error('Format des modèles inattendu.');setTemplates(r.data);}catch(error){setTemplateError(true);toast.error(getErrorMessage(error));}finally{setTemplateLoading(false);}};
  useEffect(()=>{if(!project)loadTemplates();},[project]);
  const selectedTemplate=templates.find(t=>t.id===templateId);
  const chooseTemplate=e=>{const id=e.target.value;setTemplateId(id);const t=templates.find(t=>t.id===id);if(t)setForm(v=>({...v,title:t.name,description:t.description,tags:(t.tags || []).join(', ')}));};
  const deleteTemplate=async()=>{if(!selectedTemplate || !projectConfirm('Supprimer ce modèle partagé ? Les projets déjà créés seront conservés.'))return;setBusy(true);try{await api.delete(`/animateur/projects/workspace/templates/${templateId}`);setTemplates(v=>v.filter(t=>t.id!==templateId));setTemplateId('');toast.success('Modèle supprimé.');}catch(error){toast.error(getErrorMessage(error));}finally{setBusy(false);}};
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
        ...(!project ? {template_id:templateId || null} : {}),
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
  return <Modal title={project ? 'Paramètres du projet' : 'Une nouvelle idée ?'} busy={busy} onClose={onClose}><form onSubmit={submit} className="pj-form"><p className="pj-help">Posez le cadre. Vous pourrez ensuite construire le brief et répartir les tâches avec l’équipe.</p>{!project && <div className="pj-template-picker pj-wide"><Field label="Partir d’un modèle · facultatif"><select value={templateId} disabled={busy || templateLoading} onChange={chooseTemplate}><option value="">Projet libre</option>{templates.map(t=><option key={t.id} value={t.id}>{t.builtin?'':'Équipe · '}{t.name}</option>)}</select></Field>{templateLoading && <p className="pj-help">Chargement des modèles…</p>}{templateError && <p className="pj-help">Les modèles n’ont pas pu être chargés. Vous pouvez créer un projet libre. <button type="button" className="pj-btn" onClick={loadTemplates}>Réessayer</button></p>}{selectedTemplate && <div className="pj-template-preview"><p>{selectedTemplate.description}</p><strong>{selectedTemplate.tasks.length} tâches prêtes à adapter</strong><ul>{selectedTemplate.tasks.map((task,i)=><li key={i}>{task.title}</li>)}</ul><p className="pj-help">Les échéances seront placées autour de la fin prévue, ou du début si aucune fin n’est définie. Elles ne précéderont jamais le début du projet. Les tâches vous seront attribuées, avec des checklists remises à zéro.</p>{selectedTemplate.can_delete && <button type="button" className="pj-btn pj-danger" disabled={busy} onClick={deleteTemplate}>Supprimer ce modèle</button>}</div>}</div>}<Field label="Nom du projet" wide><input required maxLength={160} value={form.title} onChange={change('title')} placeholder="Ex. Soirée jeux d’automne" /></Field><Field label="L’idée en quelques mots" wide><textarea rows={3} maxLength={4000} value={form.description} onChange={change('description')} placeholder="Quel moment souhaitez-vous créer, et pour qui ?" /></Field><Field label="Début"><input type="date" required value={form.start_date} onChange={change('start_date')} /></Field><Field label="Fin prévue · facultatif"><input type="date" min={form.start_date} value={form.end_date} onChange={change('end_date')} /></Field><Field label="Priorité"><select value={form.priority} onChange={change('priority')}>{Object.entries(PRIORITY).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field><Field label="Étiquettes · jusqu’à 8"><input maxLength={260} value={form.tags} onChange={change('tags')} placeholder="Jeux, vocal, communauté…" /></Field><footer className="pj-form-actions"><button type="button" className="pj-btn" onClick={onClose} disabled={busy}>Annuler</button><button className="pj-btn pj-primary" disabled={busy || !form.title.trim()}>{busy ? 'Enregistrement…' : project ? 'Enregistrer' : 'Créer le projet'}</button></footer></form></Modal>;
}
