import { useEffect, useMemo, useState } from 'react';
import { addDays, addMonths, endOfMonth, endOfWeek, format, isSameMonth, startOfMonth, startOfWeek } from 'date-fns';
import { fr } from 'date-fns/locale';
import { Link } from 'react-router-dom';
import { ArrowUpRight, CalendarDays, ChevronLeft, ChevronRight, Download, List } from 'lucide-react';
import { toast } from 'sonner';
import { api, getErrorMessage } from '../api/client';
import { Empty, Panel, ProjectPage } from '../components/projects/ProjectUI';
import { calendarExport, calendarItems } from '../components/projects/projectCalendar';
import { dateLabel, personName, todayKey } from '../components/projects/projectUtils';
const WEEKDAYS = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'];
export default function ProjectCalendarPage({
  helper
}) {
  const [data, setData] = useState({
    projects: [],
    tasks: []
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [month, setMonth] = useState(new Date(`${todayKey()}T12:00:00`));
  const [day, setDay] = useState(todayKey());
  const [view, setView] = useState('month');
  const [projectId, setProjectId] = useState('');
  const [mine, setMine] = useState(false);
  const [includeClosed, setIncludeClosed] = useState(false);
  const load = async () => {
    setLoading(true);
    setError(false);
    try {
      const r = await api.get('/animateur/calendar-events');
      setData(r.data);
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
  const items = useMemo(() => calendarItems(data.projects, data.tasks, {
    projectId,
    mine,
    helperId: helper?.id,
    includeClosed
  }), [data, projectId, mine, helper?.id, includeClosed]);
  const monthKey = format(month, 'yyyy-MM');
  const monthItems = items.filter(i => i.date.startsWith(monthKey));
  const days = useMemo(() => {
    const start = startOfWeek(startOfMonth(month), {
        weekStartsOn: 1
      }),
      end = endOfWeek(endOfMonth(month), {
        weekStartsOn: 1
      });
    const result = [];
    for (let d = start; d <= end; d = addDays(d, 1)) result.push(d);
    return result;
  }, [month]);
  const changeMonth = delta => {
    const next = addMonths(month, delta);
    setMonth(next);
    setDay(format(startOfMonth(next), 'yyyy-MM-dd'));
  };
  const goToday = () => {
    const today = todayKey();
    setMonth(new Date(`${today}T12:00:00`));
    setDay(today);
  };
  const projectName = id => data.projects.find(p => p.id === id)?.title;
  const itemLink = item => `/animateur/projects/${item.project_id}${item.kind === 'task' ? `?task=${encodeURIComponent(item.id)}` : ''}`;
  const itemRow = item => <Link className={`pj-agenda-row pj-event-${item.kind}`} key={item.id} to={itemLink(item)}><span className="pj-event-icon"><CalendarDays size={18} /></span><div><small>{item.label}{item.kind === 'task' && ` · ${projectName(item.project_id) || 'Projet'}`}</small><strong>{item.title}</strong>{item.assignee && <small>{personName(item.assignee)}</small>}</div><ArrowUpRight size={17} /></Link>;
  const exportMonth = () => {
    const content = calendarExport(monthItems, window.location.origin);
    const url = URL.createObjectURL(new Blob([content], {
      type: 'text/calendar;charset=utf-8'
    }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `iris-projets-${monthKey}.ics`;
    a.click();
    URL.revokeObjectURL(url);
  };
  return <ProjectPage page="calendar" title="Garder le rythme." intro="Les débuts de projets, les fins prévues et les échéances des tâches, réunis dans votre agenda." back actions={<button className="pj-btn" disabled={loading || !monthItems.length} onClick={exportMonth}><Download size={16} /> Exporter ce mois</button>}>
    <div className="pj-calendar-banner"><div><span className="pj-kicker">LES RENDEZ-VOUS DE L’ÉQUIPE</span><h2>Anticiper, sans se disperser.</h2><p>Le calendrier affiche les jalons des projets et les tâches à terminer. Sélectionnez un jour pour en voir le détail.</p></div><span><strong>{loading ? '—' : monthItems.length}</strong> jalons ce mois</span></div>
    <div className="pj-filters"><select aria-label="Projet affiché" value={projectId} onChange={e => setProjectId(e.target.value)}><option value="">Tous les projets</option>{data.projects.map(p => <option key={p.id} value={p.id}>{p.title}</option>)}</select><label className="pj-check"><input type="checkbox" checked={mine} onChange={e => setMine(e.target.checked)} /> Mes tâches uniquement</label><label className="pj-check"><input type="checkbox" checked={includeClosed} onChange={e => setIncludeClosed(e.target.checked)} /> Inclure les projets terminés, archivés et les tâches validées</label><div className="pj-chips"><button className={`pj-btn ${view === 'month' ? 'is-selected' : ''}`} aria-pressed={view === 'month'} onClick={() => setView('month')}><CalendarDays size={16} /> Mois</button><button className={`pj-btn ${view === 'agenda' ? 'is-selected' : ''}`} aria-pressed={view === 'agenda'} onClick={() => setView('agenda')}><List size={16} /> Agenda</button></div></div>
    {data.truncated && <p className="pj-notice">Le calendrier est limité aux 500 projets les plus récents et aux 5 000 premières échéances.</p>}
    {loading ? <Empty title="Votre agenda se prépare…" /> : error ? <Empty title="Le calendrier n’a pas pu être chargé."><button className="pj-btn" onClick={load}>Réessayer</button></Empty> : <div className={`pj-calendar-layout ${view === 'agenda' ? 'is-agenda' : ''}`}><section className="pj-panel"><div className="pj-calendar-head"><h2>{format(month, 'MMMM yyyy', {
              locale: fr
            })}</h2><div className="pj-inline"><button className="pj-icon" aria-label="Mois précédent" onClick={() => changeMonth(-1)}><ChevronLeft size={19} /></button><button className="pj-btn" onClick={goToday}>Aujourd’hui</button><button className="pj-icon" aria-label="Mois suivant" onClick={() => changeMonth(1)}><ChevronRight size={19} /></button></div></div>{view === 'month' ? <><div className="pj-weekdays">{WEEKDAYS.map(w => <span key={w}>{w}</span>)}</div><div className="pj-month-grid">{days.map(d => {
              const key = format(d, 'yyyy-MM-dd');
              const entries = items.filter(i => i.date === key);
              return <button key={key} aria-label={`${dateLabel(key, true)}, ${entries.length} jalon(s)`} aria-pressed={key === day} className={`pj-day ${!isSameMonth(d, month) ? 'is-outside' : ''} ${key === todayKey() ? 'is-today' : ''} ${key === day ? 'is-selected' : ''}`} onClick={() => setDay(key)}><span>{format(d, 'd')}</span><div>{entries.slice(0, 2).map(i => <span key={i.id} className={`pj-calendar-event pj-event-${i.kind}`}>{i.title}</span>)}{entries.length > 2 && <small>+{entries.length - 2} autres</small>}</div></button>;
            })}</div></> : !monthItems.length ? <Empty title="Un mois sans échéance dans cette sélection.">Modifiez les filtres ou parcourez le mois suivant.</Empty> : <div className="pj-month-agenda">{[...new Set(monthItems.map(i => i.date))].map(date => <section key={date}><h3>{dateLabel(date, true)}</h3>{monthItems.filter(i => i.date === date).map(itemRow)}</section>)}</div>}<footer className="pj-calendar-legend"><span className="pj-legend-project">Début de projet</span><span className="pj-legend-end">Fin prévue</span><span className="pj-legend-task">Échéance de tâche</span></footer></section>{view === 'month' && <aside><Panel title={dateLabel(day, true)} intro="Les jalons du jour. Ouvrez un élément pour retrouver son projet." className="pj-day-panel">{items.filter(i => i.date === day).length ? items.filter(i => i.date === day).map(itemRow) : <Empty title="Rien de prévu ce jour.">Une journée libre dans cette sélection.</Empty>}</Panel><div className="pj-tip"><h3>Votre agenda, où vous voulez.</h3><p>Exportez les jalons du mois au format calendrier (.ics). Il s’agit d’une copie à importer, à renouveler si les échéances changent.</p></div></aside>}</div>}</ProjectPage>;
}
