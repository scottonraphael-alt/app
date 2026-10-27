import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowUpRight, CheckCheck, Clock3, FolderKanban, Plus, RefreshCw, Search, Users } from 'lucide-react';
import { toast } from 'sonner';
import { api, getErrorMessage } from '../api/client';
import { Avatar, Empty, Panel, Priority, ProjectPage } from '../components/projects/ProjectUI';
import ProjectForm from '../components/projects/ProjectForm';
import { dateLabel, filterProjects, isLate, personName, progress, PROJECT_STATUS, PRIORITY } from '../components/projects/projectUtils';
export default function ProjectsListPage({
  helper
}) {
  const navigate = useNavigate();
  const [data, setData] = useState({
    projects: [],
    my_tasks: []
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [creating, setCreating] = useState(false);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('actifs');
  const [mine, setMine] = useState(false);
  const [priority, setPriority] = useState('');
  const [sort, setSort] = useState('updated');
  const [taskFilter, setTaskFilter] = useState('all');
  const load = async () => {
    setLoading(true);
    setError(false);
    try {
      const response = await api.get('/animateur/projects/workspace/overview');
      setData(response.data);
    } catch (err) {
      setError(true);
      toast.error(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    load();
  }, []);
  const projects = filterProjects(data.projects, {
    query,
    status,
    mine,
    helperId: helper?.id,
    priority,
    sort
  });
  const lateTasks = data.my_tasks.filter(t => isLate(t));
  const myTasks = data.my_tasks.filter(t => taskFilter === 'late' ? isLate(t) : taskFilter === 'review' ? t.status === 'rendu' : true);
  const active = data.projects.filter(p => p.status === 'en_cours');
  const projectTitle = id => data.projects.find(p => p.id === id)?.title || 'Projet';
  return <ProjectPage title="Les idées prennent vie." intro="Préparez vos animations, répartissez les rôles et gardez le prochain rendez-vous en vue." actions={<button className="pj-btn pj-primary" onClick={() => setCreating(true)} data-testid="new-project-button"><Plus size={17} /> Nouveau projet</button>}>
    <div className="pj-summary"><div className="pj-summary-intro"><span className="pj-kicker">L’ATELIER EN UN REGARD</span><strong>Un cap commun, chacun sa part.</strong><p>Les projets actifs et votre prochaine étape, au même endroit.</p></div><div className="pj-summary-stat"><FolderKanban size={20} /><strong>{loading ? '—' : active.length}</strong><span>projets en cours</span></div><div className="pj-summary-stat"><Users size={20} /><strong>{loading ? '—' : active.filter(p => p.members?.some(m => m.id === helper?.id)).length}</strong><span>avec vous</span></div><div className={`pj-summary-stat ${lateTasks.length ? 'pj-warm' : ''}`}><Clock3 size={20} /><strong>{loading ? '—' : lateTasks.length}</strong><span>de vos tâches en retard</span></div></div>
    {(data.projects_truncated || data.tasks_truncated) && <p className="pj-notice">Affichage limité aux 500 projets les plus récents et aux 500 premières tâches personnelles.</p>}
    <div className="pj-workspace">
      <div><div className="pj-section-heading"><div><p className="pj-kicker">EXPLORER & CONSTRUIRE</p><h2>Le carnet de projets</h2></div><button className="pj-btn" onClick={load} disabled={loading}><RefreshCw size={15} /> Actualiser</button></div>
        <div className="pj-tabs" aria-label="État des projets">{[['actifs', 'En cours'], ['termine', 'Terminés'], ['archive', 'Archives'], ['tous', 'Tous']].map(([v, l]) => <button key={v} aria-pressed={status === v} className={status === v ? 'is-active' : ''} onClick={() => setStatus(v)}>{l}<span>{data.projects.filter(p => v === 'tous' || p.status === (v === 'actifs' ? 'en_cours' : v)).length}</span></button>)}</div>
        <div className="pj-filters"><label className="pj-search"><Search size={17} /><input aria-label="Rechercher un projet" placeholder="Un projet, une idée, un membre…" value={query} onChange={e => setQuery(e.target.value)} /></label><select aria-label="Priorité des projets" value={priority} onChange={e => setPriority(e.target.value)}><option value="">Toutes les priorités</option>{Object.entries(PRIORITY).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select><select aria-label="Trier les projets" value={sort} onChange={e => setSort(e.target.value)}><option value="updated">Dernière activité</option><option value="date">Fin la plus proche</option><option value="priority">Priorité</option><option value="title">Nom du projet</option></select><button className={`pj-btn ${mine ? 'is-selected' : ''}`} aria-pressed={mine} onClick={() => setMine(v => !v)}><Users size={15} /> Mes projets</button></div>
        {loading ? <Empty title="L’atelier se prépare…">Chargement des projets et de vos tâches.</Empty> : error ? <Empty title="Impossible de charger les projets">Utilisez Actualiser pour réessayer.</Empty> : !projects.length ? <Empty title="Une page blanche, des possibilités.">{query || mine || priority ? 'Aucun projet ne correspond à vos filtres.' : status === 'actifs' ? 'Lancez une idée avec Nouveau projet.' : 'Aucun projet dans cette catégorie.'}</Empty> : <div className="pj-projects">{projects.map(project => {
            const p = progress(project.task_counts);
            return <article className={`pj-project-card pj-accent-${project.priority || 'normale'}`} key={project.id}><div className="pj-card-top"><span className="pj-project-symbol"><FolderKanban size={21} /></span><span className={`pj-badge pj-status-${project.status}`}>{PROJECT_STATUS[project.status]}</span><Priority value={project.priority} /></div><Link className="pj-project-title" to={`/animateur/projects/${project.id}`}>{project.title}<ArrowUpRight size={19} /></Link><p className="pj-card-description">{project.description || 'Le point de départ d’une prochaine animation. Le brief reste à construire.'}</p>{!!project.tags?.length && <div className="pj-tags">{project.tags.map(tag => <span key={tag}>#{tag}</span>)}</div>}<div className="pj-card-progress"><div><span>{p.total ? `${p.done} / ${p.total} tâches validées` : 'Aucune tâche pour le moment'}</span><strong>{p.percent}%</strong></div><progress value={p.percent} max="100" aria-label={`Avancement de ${project.title}`} /></div><footer><div className="pj-member-stack">{project.members?.slice(0, 4).map(m => <Avatar key={m.id} member={m} />)}{project.members?.length > 4 && <span>+{project.members.length - 4}</span>}</div><span>{project.end_date ? `Fin · ${dateLabel(project.end_date)}` : `Début · ${dateLabel(project.start_date)}`}</span></footer></article>;
          })}</div>}
      </div>
      <aside><Panel title="Mon prochain pas" intro="Vos tâches sur les projets en cours, classées par échéance." className="pj-personal"><div className="pj-chips">{[['all', 'Tout'], ['late', 'En retard'], ['review', 'À valider']].map(([v, l]) => <button className={`pj-btn ${taskFilter === v ? 'is-selected' : ''}`} key={v} onClick={() => setTaskFilter(v)} aria-pressed={taskFilter === v}>{l}</button>)}</div>{!loading && !myTasks.length ? <Empty title="Le champ est libre.">Aucune tâche dans cette sélection.</Empty> : <div className="pj-personal-list">{myTasks.slice(0, 8).map(task => <Link key={task.id} to={`/animateur/projects/${task.project_id}?task=${encodeURIComponent(task.id)}`} className="pj-personal-task"><span className={isLate(task) ? 'pj-deadline is-late' : 'pj-deadline'}>{task.status === 'rendu' ? <CheckCheck size={15} /> : <Clock3 size={15} />} {dateLabel(task.due_date)}</span><strong>{task.title}</strong><small>{projectTitle(task.project_id)} · {task.status === 'rendu' ? 'En attente de validation' : task.blocked_reason ? 'Bloquée' : personName(task.assignee)}</small></Link>)}</div>}{myTasks.length > 8 && <p className="pj-help">{myTasks.length - 8} autres tâches à retrouver dans vos projets.</p>}</Panel><div className="pj-tip"><span className="pj-kicker">LE BON RÉFLEXE</span><h3>Une tâche, un point d’arrivée.</h3><p>Un membre, une échéance et un rendu clair. Le tableau du projet vous aide à suivre le chemin jusqu’à la validation.</p><Link to="/animateur/calendrier">Voir les échéances <ArrowUpRight size={16} /></Link></div></aside>
    </div>{creating && <ProjectForm onClose={() => setCreating(false)} onSaved={project => {
      setCreating(false);
      navigate(`/animateur/projects/${project.id}`);
    }} />}</ProjectPage>;
}
