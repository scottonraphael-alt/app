import { useEffect, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Archive, ArrowUpRight, CalendarDays, CheckCheck, ClipboardList, Clock3, Download, FileText, LayoutGrid, List, MessageSquare, Pencil, Plus, Settings2, Trash2, UserMinus, UserPlus, Users } from 'lucide-react';
import { toast } from 'sonner';
import { api, getErrorMessage } from '../api/client';
import TiptapSummaryEditor from '../components/TiptapSummaryEditor';
import SummaryReader from '../components/SummaryReader';
import AddMemberModal from '../components/AddMemberModal';
import { Avatar, Empty, Field, Panel, Priority, ProjectPage } from '../components/projects/ProjectUI';
import ProjectForm from '../components/projects/ProjectForm';
import ProjectTaskDialog, { TaskForm } from '../components/projects/ProjectTaskDialog';
import { ACTIVITY_LABELS, dateLabel, isLate, personName, progress, PROJECT_STATUS, TASK_STATUS, taskCounts } from '../components/projects/projectUtils';
const TABS = [['overview', 'Vue d’ensemble', LayoutGrid], ['tasks', 'Tâches', ClipboardList], ['brief', 'Le brief', FileText], ['team', 'L’équipe', Users], ['files', 'Fichiers', Download], ['activity', 'Journal', MessageSquare]];
export default function ProjectDetailPage({
  helper,
  isResponsableGlobal
}) {
  const {
    projectId
  } = useParams();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [project, setProject] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [resources, setResources] = useState([]);
  const [activity, setActivity] = useState([]);
  const [activityLoading, setActivityLoading] = useState(false);
  const [activityError, setActivityError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [tab, setTab] = useState('overview');
  const [settings, setSettings] = useState(false);
  const [addingMember, setAddingMember] = useState(false);
  const [taskForm, setTaskForm] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [taskFilter, setTaskFilter] = useState('all');
  const [taskQuery, setTaskQuery] = useState('');
  const [taskView, setTaskView] = useState('board');
  const [editingBrief, setEditingBrief] = useState(false);
  const [content, setContent] = useState('');
  const [message, setMessage] = useState('');
  const [resourceTitle, setResourceTitle] = useState('');
  const [resourceFile, setResourceFile] = useState(null);
  const [uploadKey, setUploadKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const member = project?.created_by?.id === helper?.id || project?.members?.some(m => m.id === helper?.id);
  const manager = isResponsableGlobal || project?.created_by?.id === helper?.id;
  const canEdit = !!(member || isResponsableGlobal);
  const writable = project?.status === 'en_cours';
  const p = progress(taskCounts(tasks));
  const selected = tasks.find(t => t.id === selectedId);
  const load = async () => {
    setLoading(true);
    setFailed(false);
    try {
      const [a, b, c] = await Promise.all([api.get(`/animateur/projects/${projectId}`), api.get(`/animateur/projects/${projectId}/tasks`), api.get(`/animateur/projects/${projectId}/resources`)]);
      setProject(a.data);
      setContent(a.data.content_markdown || '');
      setTasks(b.data);
      setResources(c.data);
    } catch (error) {
      setFailed(true);
      toast.error(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    setTab('overview');
    setEditingBrief(false);
    setSelectedId(null);
    load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */
  }, [projectId]);
  const taskParam = params.get('task');
  useEffect(() => {
    if (taskParam && tasks.some(t => t.id === taskParam)) {
      setSelectedId(taskParam);
      setTab('tasks');
    }
  }, [taskParam, tasks]);
  const closeTask = () => {
    setSelectedId(null);
    if (taskParam) {
      const next = new URLSearchParams(params);
      next.delete('task');
      setParams(next, {
        replace: true
      });
    }
  };
  const updateTask = task => setTasks(v => v.some(t => t.id === task.id) ? v.map(t => t.id === task.id ? task : t) : [...v, task]);
  const loadActivity = async () => {
    setActivityLoading(true);
    setActivityError(false);
    try {
      const r = await api.get(`/animateur/projects/${projectId}/activity`);
      setActivity(r.data);
    } catch (error) {
      setActivityError(true);
      toast.error(getErrorMessage(error));
    } finally {
      setActivityLoading(false);
    }
  };
  useEffect(() => {
    if (tab === 'activity' && canEdit) loadActivity(); /* eslint-disable-next-line react-hooks/exhaustive-deps */
  }, [tab, projectId, canEdit]);
  const act = async operation => {
    setBusy(true);
    try {
      await operation();
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setBusy(false);
    }
  };
  const changeStatus = status => act(async () => {
    if (status === 'archive' && !window.confirm('Archiver le projet ? Il restera consultable, puis pourra être restauré.')) return;
    const r = await api.patch(`/animateur/projects/${projectId}/settings`, {
      status
    });
    setProject(r.data);
    toast.success('État du projet mis à jour.');
  });
  const saveBrief = () => act(async () => {
    const r = await api.patch(`/animateur/projects/${projectId}/brief`, {
      content_markdown: content
    });
    setProject(r.data);
    setEditingBrief(false);
    toast.success('Brief enregistré.');
  });
  const upload = e => {
    e.preventDefault();
    if (!resourceFile) return;
    act(async () => {
      const form = new FormData();
      form.append('title', resourceTitle.trim() || resourceFile.name);
      form.append('file', resourceFile);
      const r = await api.post(`/animateur/projects/${projectId}/resources`, form);
      setResources(v => [r.data, ...v]);
      setResourceTitle('');
      setResourceFile(null);
      setUploadKey(v => v + 1);
      toast.success('Fichier ajouté.');
    });
  };
  const download = resource => act(async () => {
    const r = await api.get(`/animateur/resources/${resource.id}/download`, {
      responseType: 'blob'
    });
    const url = URL.createObjectURL(r.data);
    const a = document.createElement('a');
    a.href = url;
    a.download = resource.original_filename;
    a.click();
    URL.revokeObjectURL(url);
  });
  const filtered = tasks.filter(t => (!taskQuery || `${t.title} ${t.description} ${personName(t.assignee)}`.toLowerCase().includes(taskQuery.toLowerCase())) && (taskFilter === 'mine' ? t.assignee?.id === helper?.id : taskFilter === 'late' ? isLate(t) : taskFilter === 'blocked' ? !!t.blocked_reason : taskFilter === 'review' ? t.status === 'rendu' : true)).sort((a, b) => (a.due_date || '').localeCompare(b.due_date || ''));
  const taskCard = task => <button key={task.id} className="pj-task-card" onClick={() => setSelectedId(task.id)}><div className="pj-inline"><Priority value={task.priority} />{task.blocked_reason && <span className="pj-badge pj-alert">Bloquée</span>}</div><strong>{task.title}</strong>{task.description && <p>{task.description}</p>}<footer><span className="pj-task-assignee"><Avatar member={task.assignee} /><span>{personName(task.assignee)}</span></span><span className={`pj-deadline ${isLate(task) ? 'is-late' : ''}`}>{isLate(task) && <Clock3 size={13} />} {dateLabel(task.due_date)}</span></footer></button>;
  if (loading || failed || !project) return <ProjectPage title="L’atelier du projet" back intro="Chaque étape compte."><Empty title={loading ? 'Chargement du projet…' : 'Le projet n’a pas pu être chargé.'}>{!loading && <button className="pj-btn" onClick={load}>Réessayer</button>}</Empty></ProjectPage>;
  return <ProjectPage title={project.title} intro={project.description || 'Une idée à construire ensemble, du premier brief au dernier détail.'} back actions={manager && writable && <button className="pj-btn" onClick={() => setSettings(true)}><Settings2 size={16} /> Paramètres</button>}>
    <div className="pj-project-meta"><span className={`pj-badge pj-status-${project.status}`}>{PROJECT_STATUS[project.status]}</span><Priority value={project.priority} /><span><CalendarDays size={16} /> {dateLabel(project.start_date)} → {dateLabel(project.end_date)}</span><span><Users size={16} /> {project.members.length} membre{project.members.length > 1 ? 's' : ''}</span><span>Piloté par {personName(project.created_by)}</span>{project.tags?.map(tag => <span className="pj-tag" key={tag}>#{tag}</span>)}</div>
    {!writable && <div className="pj-notice pj-archive"><Archive size={19} /><p>{project.status === 'archive' ? 'Ce projet est archivé.' : 'Ce projet est terminé.'} Les documents et les rendus restent consultables.</p>{manager && <button className="pj-btn" disabled={busy} onClick={() => changeStatus('en_cours')}>{project.status === 'archive' ? 'Restaurer le projet' : 'Rouvrir le projet'}</button>}</div>}
    {!canEdit && writable && <div className="pj-notice"><p>Envie de contribuer ? Rejoignez l’équipe pour participer au brief et déposer des fichiers.</p><button className="pj-btn pj-primary" disabled={busy} onClick={() => act(async () => {
        const r = await api.post(`/animateur/projects/${projectId}/members`, {
          member_id: helper.id
        });
        setProject(r.data);
        toast.success('Bienvenue dans l’équipe !');
      })}><UserPlus size={16} /> Rejoindre</button></div>}
    <nav className="pj-tabs pj-detail-tabs" aria-label="Rubriques du projet">{TABS.filter(([key]) => key !== 'activity' || canEdit).map(([key, label, Icon]) => <button key={key} className={tab === key ? 'is-active' : ''} aria-current={tab === key ? 'page' : undefined} onClick={() => {
        if (editingBrief && tab === 'brief' && key !== 'brief' && !window.confirm('Quitter le brief sans enregistrer ?')) return;
        if (key !== 'brief') setEditingBrief(false);
        setTab(key);
      }}><Icon size={16} />{label}{key === 'tasks' && <span>{tasks.length}</span>}</button>)}</nav>
    {tab === 'overview' && <div className="pj-detail-grid"><div><Panel title="Le cap du projet" intro="Le contexte et les décisions utiles, avant de passer à l’action." actions={<button className="pj-btn" onClick={() => setTab('brief')}>Ouvrir le brief <ArrowUpRight size={15} /></button>}><div className="pj-brief-excerpt">{project.content_markdown ? <SummaryReader key={project.updated_at} content={project.content_markdown} /> : <Empty title="Tout commence par une intention.">Précisez l’objectif, le public et le déroulé dans le brief du projet.</Empty>}</div></Panel><Panel title="Les prochaines étapes" intro="Les tâches à faire ou en cours, classées par échéance." actions={<button className="pj-btn" onClick={() => setTab('tasks')}>Toutes les tâches <ArrowUpRight size={15} /></button>}>{!tasks.some(t => ['a_faire', 'en_cours'].includes(t.status)) ? <Empty title="Le chemin est dégagé.">Aucune tâche à faire ou en cours.</Empty> : <div className="pj-next-tasks">{tasks.filter(t => ['a_faire', 'en_cours'].includes(t.status)).sort((a, b) => (a.due_date || '').localeCompare(b.due_date || '')).slice(0, 4).map(taskCard)}</div>}</Panel></div><aside><Panel title="Où en sommes-nous ?" intro="L’avancement repose sur les tâches validées."><div className="pj-big-progress"><strong>{p.percent}<small>%</small></strong><p>{p.done} tâche{p.done > 1 ? 's' : ''} validée{p.done > 1 ? 's' : ''} sur {p.total}</p><progress value={p.percent} max={100} aria-label="Progression du projet" /></div><div className="pj-stats-rows"><button onClick={() => {
              setTaskFilter('late');
              setTab('tasks');
            }}><span>En retard</span><strong>{tasks.filter(t => isLate(t)).length}</strong></button><button onClick={() => {
              setTaskFilter('blocked');
              setTab('tasks');
            }}><span>Bloquées</span><strong>{tasks.filter(t => !!t.blocked_reason && t.status !== 'valide').length}</strong></button><button onClick={() => {
              setTaskFilter('review');
              setTab('tasks');
            }}><span>À valider</span><strong>{tasks.filter(t => t.status === 'rendu').length}</strong></button></div>{manager && writable && <div className="pj-lifecycle"><button className="pj-btn" disabled={busy || project.status !== 'termine' && p.done !== p.total} onClick={() => changeStatus(project.status === 'termine' ? 'en_cours' : 'termine')}><CheckCheck size={16} />{project.status === 'termine' ? 'Rouvrir le projet' : 'Terminer le projet'}</button><p className="pj-help">Validez toutes les tâches pour terminer le projet.</p><button className="pj-btn" disabled={busy} onClick={() => changeStatus('archive')}><Archive size={16} /> Archiver</button></div>}</Panel><Panel title="Une équipe, un projet" intro={`${project.members.length} personnes réunies autour de cette idée.`}><div className="pj-member-list">{project.members.slice(0, 5).map(m => <div className="pj-member" key={m.id}><Avatar member={m} /><strong>{personName(m)}</strong><small>{m.id === project.created_by.id ? 'Pilote' : 'Équipe'}</small></div>)}</div><button className="pj-btn" onClick={() => setTab('team')}>Voir l’équipe</button></Panel></aside></div>}
    {tab === 'tasks' && <><div className="pj-section-heading"><div><h2>De l’idée au résultat</h2><p className="pj-help">Ouvrez une carte pour avancer, signaler un blocage ou présenter un rendu. Le pilote valide le travail.</p></div>{manager && writable && <button className="pj-btn pj-primary" onClick={() => setTaskForm({})}><Plus size={16} /> Ajouter une tâche</button>}</div><div className="pj-filters"><input aria-label="Rechercher une tâche" placeholder="Une tâche, un membre…" value={taskQuery} onChange={e => setTaskQuery(e.target.value)} /><select aria-label="Filtrer les tâches" value={taskFilter} onChange={e => setTaskFilter(e.target.value)}><option value="all">Toutes les tâches</option><option value="mine">Mes tâches</option><option value="late">En retard</option><option value="blocked">Bloquées</option><option value="review">À valider</option></select><div className="pj-chips"><button className={`pj-btn ${taskView === 'board' ? 'is-selected' : ''}`} onClick={() => setTaskView('board')} aria-pressed={taskView === 'board'}><LayoutGrid size={15} /> Tableau</button><button className={`pj-btn ${taskView === 'list' ? 'is-selected' : ''}`} onClick={() => setTaskView('list')} aria-pressed={taskView === 'list'}><List size={15} /> Liste</button></div></div>{!filtered.length ? <Empty title={tasks.length ? 'Aucune tâche dans cette sélection.' : 'Le projet attend ses premières étapes.'}>{manager && writable ? 'Ajoutez une tâche pour répartir le travail.' : 'Les tâches apparaîtront ici une fois créées.'}</Empty> : taskView === 'board' ? <div className="pj-board">{Object.entries(TASK_STATUS).map(([key, label]) => <section key={key} className={`pj-board-column pj-column-${key}`}><header><h3>{label}</h3><span>{filtered.filter(t => t.status === key).length}</span></header><div>{filtered.filter(t => t.status === key).map(taskCard)}{!filtered.some(t => t.status === key) && <p className="pj-column-empty">Rien ici pour le moment.</p>}</div></section>)}</div> : <div className="pj-task-list">{filtered.map(t => <div key={t.id}><span className={`pj-badge pj-task-${t.status}`}>{TASK_STATUS[t.status]}</span>{taskCard(t)}</div>)}</div>}</>}
    {tab === 'brief' && <Panel title="Le brief partagé" intro="L’objectif, le déroulé, le matériel et les décisions de l’équipe." actions={canEdit && writable && <div className="pj-inline">{editingBrief ? <><button className="pj-btn" disabled={busy} onClick={() => {
          setContent(project.content_markdown || '');
          setEditingBrief(false);
        }}>Annuler</button><button className="pj-btn pj-primary" disabled={busy} onClick={saveBrief}>{busy ? 'Enregistrement…' : 'Enregistrer le brief'}</button></> : <button className="pj-btn" onClick={() => {
        setContent(project.content_markdown || '');
        setEditingBrief(true);
      }}><Pencil size={15} /> Modifier le brief</button>}</div>}>{editingBrief ? <TiptapSummaryEditor value={content} onChange={setContent} placeholder="Objectif, public, déroulé, matériel… Tapez / pour les outils." /> : project.content_markdown ? <SummaryReader key={project.updated_at} content={project.content_markdown} /> : <Empty title="Le point de départ du projet.">Notez ce que vous souhaitez créer, puis enrichissez le brief ensemble.</Empty>}</Panel>}
    {tab === 'team' && <Panel title="Les personnes derrière le projet" intro="Le pilote organise le projet. Chaque membre peut enrichir le brief, déposer des fichiers et avancer sur ses tâches." actions={manager && writable && <button className="pj-btn pj-primary" onClick={() => setAddingMember(true)}><UserPlus size={16} /> Ajouter un animateur</button>}><div className="pj-team-grid">{project.members.map(m => {
          const assigned = tasks.filter(t => t.assignee?.id === m.id);
          return <article className="pj-team-card" key={m.id}><Avatar member={m} /><h3>{personName(m)}</h3><span className="pj-badge">{m.id === project.created_by.id ? 'Pilote du projet' : 'Équipe'}</span><p>{assigned.filter(t => t.status !== 'valide').length} tâche(s) ouverte(s) · {assigned.filter(t => t.status === 'valide').length} validée(s)</p>{manager && writable && m.id !== project.created_by.id && <button className="pj-btn pj-danger" disabled={busy} onClick={() => {
              if (window.confirm(`Retirer ${personName(m)} du projet ? Ses tâches ouvertes doivent d’abord être réattribuées.`)) act(async () => {
                const r = await api.delete(`/animateur/projects/${projectId}/members/${m.id}`);
                setProject(r.data);
              });
            }}><UserMinus size={15} /> Retirer</button>}</article>;
        })}</div></Panel>}
    {tab === 'files' && <Panel title="Tout le nécessaire" intro="Centralisez les supports, visuels et documents utiles. Les fichiers des rendus restent dans leurs tâches.">{canEdit && writable && <form onSubmit={upload} className="pj-upload"><Field label="Nom du document"><input value={resourceTitle} maxLength={160} onChange={e => setResourceTitle(e.target.value)} placeholder="Ex. Visuel de l’événement" /></Field><Field label="Choisir un fichier"><input key={uploadKey} type="file" required onChange={e => setResourceFile(e.target.files?.[0] || null)} /></Field><button className="pj-btn pj-primary" disabled={busy || !resourceFile}><Plus size={16} />{busy ? 'Envoi…' : 'Ajouter le fichier'}</button></form>}{!resources.length ? <Empty title="Les supports trouveront leur place ici.">Ajoutez les documents dont l’équipe a besoin.</Empty> : <div className="pj-files">{resources.map(resource => <div className="pj-file" key={resource.id}><FileText size={24} /><div><strong>{resource.title}</strong><small>{resource.original_filename} · {(resource.size / 1024).toFixed(0)} Ko · {personName(resource.uploaded_by)}</small></div>{canEdit && <button className="pj-btn" disabled={busy} onClick={() => download(resource)}><Download size={15} /> Télécharger</button>}{manager && writable && <button className="pj-icon pj-danger" aria-label={`Supprimer ${resource.title}`} disabled={busy} onClick={() => {
            if (window.confirm('Supprimer ce fichier du projet ?')) act(async () => {
              await api.delete(`/animateur/resources/${resource.id}`);
              setResources(v => v.filter(r => r.id !== resource.id));
            });
          }}><Trash2 size={16} /></button>}</div>)}</div>}</Panel>}
    {tab === 'activity' && canEdit && <Panel title="Le fil de l’équipe" intro="Partagez une décision ou un point d’étape. Les dernières actions complètent ce journal ; les responsables disposent aussi des logs IRIS.">{writable && <form className="pj-comment" onSubmit={e => {
        e.preventDefault();
        act(async () => {
          await api.post(`/animateur/projects/${projectId}/activity`, {
            message
          });
          setMessage('');
          await loadActivity();
        });
      }}><Field label="Un point à partager avec l’équipe"><textarea maxLength={2000} rows={3} required value={message} onChange={e => setMessage(e.target.value)} placeholder="Une décision prise, un détail à ne pas oublier…" /></Field><button className="pj-btn pj-primary" disabled={busy || !message.trim()}>Publier dans le journal</button></form>}{activityLoading ? <Empty title="Chargement du journal…" /> : activityError ? <Empty title="Le journal n’a pas pu être chargé."><button className="pj-btn" onClick={loadActivity}>Réessayer</button></Empty> : !activity.length ? <Empty title="Les premières traces de l’équipe.">Vos points d’étape et les actions du projet apparaîtront ici.</Empty> : <ol className="pj-timeline">{activity.map(a => <li key={a.id}><span className={`pj-timeline-dot ${a.event_type === 'project.comment.added' ? 'is-note' : ''}`} /><div><p><strong>{a.username || 'Un membre'}</strong> {ACTIVITY_LABELS[a.event_type] || 'a mis à jour le projet'}{a.details?.title && ` · ${a.details.title}`}</p><time>{new Date(a.created_at).toLocaleString('fr-FR', {
                timeZone: 'Europe/Paris',
                dateStyle: 'medium',
                timeStyle: 'short'
              })}</time>{a.details?.message && <blockquote>{a.details.message}</blockquote>}</div></li>)}</ol>}</Panel>}
    {isResponsableGlobal && tab === 'overview' && <details className="pj-danger-zone"><summary>Administration du projet</summary><p>La suppression efface le projet, ses tâches et ses fichiers associés. Préférez l’archivage pour conserver le travail de l’équipe.</p><button className="pj-btn pj-danger" disabled={busy} onClick={() => {
        if (window.confirm(`Supprimer définitivement « ${project.title} » et toutes ses tâches ?`)) act(async () => {
          await api.delete(`/animateur/projects/${projectId}`);
          navigate('/animateur/projects');
        });
      }}>Supprimer définitivement</button></details>}
    {settings && <ProjectForm project={project} onClose={() => setSettings(false)} onSaved={updated => {
      setProject(updated);
      setSettings(false);
    }} />} {addingMember && <AddMemberModal projectId={projectId} existingIds={project.members.map(m => m.id)} onAdded={setProject} onClose={() => setAddingMember(false)} />}
    {taskForm && <TaskForm project={project} task={taskForm.id ? taskForm : undefined} onClose={() => setTaskForm(null)} onSaved={task => {
      updateTask(task);
      setTaskForm(null);
    }} />} {selected && !taskForm && <ProjectTaskDialog key={selected.id} task={selected} helper={helper} manager={manager} members={project.members} writable={writable} onSaved={updateTask} onClose={closeTask} onEdit={() => setTaskForm(selected)} onDelete={id => {
      setTasks(v => v.filter(t => t.id !== id));
      closeTask();
    }} />}</ProjectPage>;
}
