import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { api, getErrorMessage } from '../api/client';
import { Empty, ProjectPage } from '../components/projects/ProjectUI';
import { dateLabel } from '../components/projects/projectUtils';

const DAY = 86400000;
const t = s => new Date(`${s}T12:00:00Z`).getTime();

export default function ProjectsTimelinePage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [closed, setClosed] = useState(false);
  const load = async () => {
    setLoading(true); setFailed(false);
    try { setData((await api.get('/project-extras/timeline', { params: { include_closed: closed } })).data); }
    catch (error) { setFailed(true); toast.error(getErrorMessage(error)); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [closed]); // eslint-disable-line react-hooks/exhaustive-deps
  const view = useMemo(() => {
    if (!data?.range?.start) return null;
    const lo = t(data.range.start) - 2 * DAY;
    const hi = Math.max(t(data.range.end), t(data.today)) + 2 * DAY;
    const span = Math.max(hi - lo, DAY);
    const pos = (a, b) => ({ left: `${(t(a) - lo) / span * 100}%`, width: `${Math.max((t(b) - t(a) + DAY) / span * 100, 1.2)}%` });
    return { pos, today: `${(t(data.today) - lo) / span * 100}%`, days: Math.round(span / DAY) };
  }, [data]);
  return <ProjectPage title="Chronologie des projets" intro="Les projets et leurs tâches sur une ligne de temps." page="timeline" actions={<><Link className="pj-btn" to="/animateur/projects">Liste des projets</Link><button className="pj-btn" onClick={load} disabled={loading}><RefreshCw size={15} /> Actualiser</button></>}>
    <label className="pj-help pj-tl-toggle"><input type="checkbox" checked={closed} onChange={e => setClosed(e.target.checked)} /> Inclure les projets terminés et archivés</label>
    {loading && <p className="pj-help" role="status">Chargement de la chronologie…</p>}
    {failed && <Empty title="La chronologie n’a pas pu être chargée."><button className="pj-btn" onClick={load}>Réessayer</button></Empty>}
    {!loading && !failed && !view && <Empty title="Aucun projet à afficher.">Créez un projet avec des tâches datées pour le voir ici.</Empty>}
    {!loading && view && <div className="pj-tl" role="list" aria-label="Projets sur la chronologie">
      <p className="pj-help">Du {dateLabel(data.range.start)} au {dateLabel(data.range.end)} · {view.days} jours · repère vertical : aujourd’hui</p>
      {data.projects.map(p => <section key={p.id} role="listitem" className="pj-tl-project">
        <header><Link to={`/animateur/projects/${p.id}`}>{p.title}</Link><span>{p.progress.percent} % · {p.progress.done}/{p.progress.total} tâches</span></header>
        <div className="pj-tl-track"><span className="pj-tl-today" style={{ left: view.today }} aria-hidden="true" /><span className="pj-tl-bar pj-tl-project-bar" style={view.pos(p.start, p.end)} title={`${dateLabel(p.start)} → ${dateLabel(p.end)}`}><i style={{ width: `${p.progress.percent}%` }} /></span></div>
        {p.tasks.map(k => <div key={k.id} className="pj-tl-row"><span className="pj-tl-label" title={k.title}>{k.title}{k.subtasks.total ? ` (${k.subtasks.done}/${k.subtasks.total})` : ''}</span>
          <div className="pj-tl-track"><span className="pj-tl-today" style={{ left: view.today }} aria-hidden="true" /><span className={`pj-tl-bar pj-tl-${k.status}`} style={view.pos(k.start, k.end)} title={`${dateLabel(k.start)} → ${dateLabel(k.end)}`}><i style={{ width: `${k.subtasks.percent}%` }} /></span></div></div>)}
      </section>)}
    </div>}
  </ProjectPage>;
}
