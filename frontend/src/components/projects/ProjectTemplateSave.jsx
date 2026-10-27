import { useState } from 'react';
import { toast } from 'sonner';
import { api, getErrorMessage } from '../../api/client';
import { Field, Modal } from './ProjectUI';

export default function ProjectTemplateSave({project,onClose}) {
  const [name,setName]=useState(project.title.slice(0,100));
  const [busy,setBusy]=useState(false);
  const save=async e=>{
    e.preventDefault();setBusy(true);
    try {await api.post(`/animateur/projects/${project.id}/template`,{name:name.trim()});toast.success('Modèle partagé enregistré. Retrouvez-le dans Nouveau projet.');onClose();}
    catch(error){toast.error(getErrorMessage(error));}finally{setBusy(false);}
  };
  return <Modal title="Garder une bonne recette" onClose={onClose} busy={busy}><form className="pj-form" onSubmit={save}><p className="pj-help">Ce modèle sera disponible à toute l’équipe d’animation. Il conservera le brief, les étiquettes, les tâches et leurs checklists. Les membres, rendus, fichiers, notes et bilan resteront dans le projet d’origine.</p><Field label="Nom du modèle partagé" wide><input required maxLength={100} value={name} onChange={e=>setName(e.target.value)}/></Field><footer className="pj-form-actions"><button type="button" className="pj-btn" disabled={busy} onClick={onClose}>Annuler</button><button className="pj-btn pj-primary" disabled={busy || !name.trim()}>{busy?'Enregistrement…':'Enregistrer le modèle'}</button></footer></form></Modal>;
}
