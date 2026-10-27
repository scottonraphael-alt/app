import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Search, UserPlus } from 'lucide-react';
import { api, getErrorMessage } from '../api/client';
import { Avatar, Empty, Modal } from './projects/ProjectUI';
import { personName } from './projects/projectUtils';
export default function AddMemberModal({
  projectId,
  existingIds,
  onAdded,
  onClose
}) {
  const [pool, setPool] = useState([]),
    [loading, setLoading] = useState(true),
    [query, setQuery] = useState(''),
    [busy, setBusy] = useState(false),
    [failed, setFailed] = useState(false);
  const load = async () => {
    setLoading(true);
    setFailed(false);
    try {
      const r = await api.get('/animateur/members/search');
      setPool(r.data);
    } catch (error) {
      setFailed(true);
      toast.error(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    load();
  }, []);
  const results = pool.filter(m => !existingIds.includes(m.id) && `${personName(m)} ${m.username}`.toLowerCase().includes(query.toLowerCase())).slice(0, 50);
  const add = async member => {
    setBusy(true);
    try {
      const r = await api.post(`/animateur/projects/${projectId}/members`, {
        member_id: member.id
      });
      onAdded(r.data);
      toast.success(`${personName(member)} a rejoint le projet.`);
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setBusy(false);
    }
  };
  return <Modal title="Construire l’équipe" onClose={onClose} busy={busy}><div className="pj-task-detail"><p className="pj-help">Retrouvez les membres disposant du rôle Animateur sur Discord.</p><label className="pj-search"><Search size={17} /><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Un nom, un pseudo…" aria-label="Rechercher un animateur" /></label>{loading ? <Empty title="Recherche des animateurs…" /> : failed ? <Empty title="La liste n’a pas pu être chargée."><button className="pj-btn" onClick={load}>Réessayer</button></Empty> : !results.length ? <Empty title="Aucun animateur à ajouter.">Modifiez la recherche ou vérifiez les membres déjà présents.</Empty> : <div className="pj-member-list">{results.map(m => <div className="pj-member" key={m.id}><Avatar member={m} /><div><strong>{personName(m)}</strong><small>@{m.username}</small></div><button className="pj-btn" disabled={busy} onClick={() => add(m)}><UserPlus size={15} /> Ajouter</button></div>)}</div>}</div></Modal>;
}
