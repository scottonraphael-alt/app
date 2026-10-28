import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowUpRight, CheckCheck, Clock3, FolderKanban, Plus, RefreshCw, Search, Users } from 'lucide-react';
import { toast } from 'sonner';
import { api, getErrorMessage } from '../api/client';
import { Avatar, Empty, Panel, Priority, ProjectPage, Pagination, usePage } from '../components/projects/ProjectUI';
import ProjectReminderSettings from '../components/projects/ProjectReminderSettings';
import ProjectForm from '../components/projects/ProjectForm';
import ProjectTemplateBuilder from '../components/projects/ProjectTemplateBuilder';
import { dateLabel, filterProjects, isLate, personName, progress, PROJECT_STATUS, PRIORITY } from '../components/projects/projectUtils';
export default function ProjectsListPage({
  helper, isResponsableGlobal
}) {
  const navigate = useNavigate();
  const [data, setData] = useState({
    projects: [],
    my_tasks: []
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [showReminders,setShowReminders]=useState(false);
  const [creating, setCreating] = useState(false);
  const [buildingTemplate, setBuildingTemplate] = useState(false);
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
  const projectPages = usePage(projects, 8, `${query}|${status}|${mine}|${priority}|${sort}`);
  const personalPages = usePage(myTasks, 5, taskFilter);
  const active = data.projects.filter(p => p.status === 'en_cours');
  const projectTitle = id => data.projects.find(p => p.id === id)?.title || 'Projet';
  return <ProjectPage title="Les idées prennent vie." intro="Préparez vos animations, répartissez les rôles et gardez le prochain rendez-vous en vue." actions={<><Link className="pj-btn" to="/animateur/projects/chronologie">Chronologie</Link><button className="pj-btn" onClick={()=>setBuildingTemplate(true)}>Nouveau modèle</button>{isResponsableGlobal && <button className="pj-btn" onClick={()=>setShowReminders(true)}><Clock3 size={16}/> Rappels Discord</button>}<button className="pj-btn pj-primary" onClick={() => setCreating(true)} data-testid="new-project-button"><Plus size={17} /> Nouveau projet</button></>}>
    <div className="pj-summary-heading"><p className="pj-kicker">L’ATELIER EN UN REGARD</p></div>
    <div className="pj-summary">
      <div className="pj-summary-stat"><span className="pj-counter-icon"><FolderKanban size={21}/></span><div><strong>{loading ? '—' : active.length}</strong><span>Projets en cours</span></div></div>
      <div className="pj-summary-stat"><span className="pj-counter-icon"><Users size={21}/></span><div><strong>{loading ? '—' : active.filter(p => p.members?.some(m => m.id === helper?.id)).length}</strong><span>Mes projets actifs</span></div></div>
      <div className={`pj-summary-stat ${lateTasks.length ? 'pj-warm' : ''}`}><span className="pj-counter-icon"><Clock3 size={21}/></span><div><strong>{loading ? '—' : lateTasks.length}</strong><span>Mes tâches en retard</span></div></div>
    </div>
    {(data.projects_truncated || data.tasks_truncated) && <p className="pj-notice">Affichage limité aux 500 projets les plus récents et aux 500 premières tâches personnelles.</p>}
    <div className="pj-workspace">
      <div><div className="pj-section-heading"><div><p className="pj-kicker">EXPLORER & CONSTRUIRE</p><h2>Le carnet de projets</h2></div><button className="pj-btn" onClick={load} disabled={loading}><RefreshCw size={15} /> Actualiser</button></div>
        <div className="pj-tabs" aria-label="État des projets">{[['actifs', 'En cours'], ['termine', 'Terminés'], ['archive', 'Archives'], ['tous', 'Tous']].map(([v, l]) => <button key={v} aria-pressed={status === v} className={status === v ? 'is-active' : ''} onClick={() => setStatus(v)}>{l}<span>{data.projects.filter(p => v === 'tous' || p.status === (v === 'actifs' ? 'en_cours' : v)).length}</span></button>)}</div>
        <div className="pj-filters"><label className="pj-search"><Search size={17} /><input aria-label="Rechercher un projet" placeholder="Un projet, une idée, un membre…" value={query} onChange={e => setQuery(e.target.value)} /></label><select aria-label="Priorité des projets" value={priority} onChange={e => setPriority(e.target.value)}><option value="">Toutes les priorités</option>{Object.entries(PRIORITY).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select><select aria-label="Trier les projets" value={sort} onChange={e => setSort(e.target.value)}><option value="updated">Dernière activité</option><option value="date">Fin la plus proche</option><option value="priority">Priorité</option><option value="title">Nom du projet</option></select><button className={`pj-btn ${mine ? 'is-selected' : ''}`} aria-pressed={mine} onClick={() => setMine(v => !v)}><Users size={15} /> Mes projets</button></div>
        {loading ? <Empty title="L’atelier se prépare…">Chargement des projets et de vos tâches.</Empty> : error ? <Empty title="Impossible de charger les projets">Utilisez Actualiser pour réessayer.</Empty> : !projects.length ? <Empty title="Une page blanche, des possibilités.">{query || mine || priority ? 'Aucun projet ne correspond à vos filtres.' : status === 'actifs' ? 'Lancez une idée avec Nouveau projet.' : 'Aucun projet dans cette catégorie.'}</Empty> : <div className="pj-project-list">
          <div className="pj-project-list-head" aria-hidden="true"><span>Projet</span><span>Avancement</span><span>Équipe</span><span>Échéance</span><span/></div>
          {projectPages.items.map(project => {
            const p = progress(project.task_counts);
            return <Link className="pj-project-row" key={project.id} to={`/animateur/projects/${project.id}`}>
              <div className="pj-row-copy"><div className="pj-row-title"><strong title={project.title}>{project.title}</strong><span className={`pj-badge pj-status-${project.status}`}>{PROJECT_STATUS[project.status]}</span>{project.priority === 'haute' && <Priority value={project.priority}/>}</div><p title={project.description}>{project.description || 'Le brief reste à construire.'}</p>{!!project.tags?.length && <span className="pj-row-tags">{project.tags.map(tag => `#${tag}`).join(' · ')}</span>}</div>
              <div className="pj-row-progress"><span>{p.done} / {p.total} validées <strong>{p.percent}%</strong></span><progress value={p.percent} max="100" aria-label={`Avancement de ${project.title}`}/></div>
              <div className="pj-member-stack" aria-label={`${project.members?.length || 0} membres`}>{project.members?.slice(0,3).map(m => <Avatar key={m.id} member={m}/>)}{project.members?.length > 3 && <span>+{project.members.length - 3}</span>}</div>
              <span className="pj-row-date"><small>{project.end_date ? 'Fin prévue' : 'Début'}</small>{dateLabel(project.end_date || project.start_date)}</span><ArrowUpRight size={17} aria-hidden="true"/>
            </Link>;
          })}
          <Pagination page={projectPages.page} pageSize={8} total={projects.length} onChange={projectPages.setPage} label="projets"/>
        </div>}

      </div>
      <aside><Panel title="Mon prochain pas" intro="Vos tâches sur les projets en cours, classées par échéance." className="pj-personal"><div className="pj-chips">{[['all', 'Tout'], ['late', 'En retard'], ['review', 'À valider']].map(([v, l]) => <button className={`pj-btn ${taskFilter === v ? 'is-selected' : ''}`} key={v} onClick={() => setTaskFilter(v)} aria-pressed={taskFilter === v}>{l}</button>)}</div>{!loading && !myTasks.length ? <Empty title="Le champ est libre.">Aucune tâche dans cette sélection.</Empty> : <div className="pj-personal-list">{personalPages.items.map(task => <Link key={task.id} to={`/animateur/projects/${task.project_id}?task=${encodeURIComponent(task.id)}`} className={`pj-personal-task ${task.blocked_reason ? 'is-blocked' : ''}`}><span className={isLate(task) ? 'pj-deadline is-late' : 'pj-deadline'}>{task.status === 'rendu' ? <CheckCheck size={15} /> : <Clock3 size={15} />} {dateLabel(task.due_date)}</span><strong title={task.title}>{task.title}</strong><small>{projectTitle(task.project_id)} · {task.status === 'rendu' ? 'En attente de validation' : task.blocked_reason ? 'Bloquée' : personName(task.assignee)}</small></Link>)}</div>}<Pagination page={personalPages.page} pageSize={5} total={myTasks.length} onChange={personalPages.setPage} label="tâches personnelles"/></Panel><div className="pj-tip"><span className="pj-kicker">LE BON RÉFLEXE</span><h3>Une tâche, un point d’arrivée.</h3><p>Un membre, une échéance et un rendu clair. Le tableau du projet vous aide à suivre le chemin jusqu’à la validation.</p><Link to="/staff/calendrier?categorie=taches">Voir les échéances <ArrowUpRight size={16} /></Link></div></aside>
    </div>{buildingTemplate && <ProjectTemplateBuilder onClose={()=>setBuildingTemplate(false)}/>}{showReminders && <ProjectReminderSettings onClose={()=>setShowReminders(false)}/>} {creating && <ProjectForm onClose={() => setCreating(false)} onSaved={project => {
      setCreating(false);
      navigate(`/animateur/projects/${project.id}`);
    }} />}</ProjectPage>;
}
