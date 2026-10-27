import { Clock3, ArrowUpRight } from 'lucide-react';
import { Avatar, Pagination, Priority, usePage } from './ProjectUI';
import { dateLabel, isLate, personName, TASK_STATUS } from './projectUtils';

export default function ProjectTasksList({ tasks, onOpen, resetKey }) {
  const { items, page, setPage } = usePage(tasks, 8, resetKey);
  return <div className="pj-task-table">
    <div className="pj-task-table-head" aria-hidden="true"><span>Tâche</span><span>Attribuée à</span><span>Échéance</span><span>État</span><span/></div>
    <ul>{items.map(task => <li key={task.id}>
      <button className={`pj-task-row ${task.blocked_reason ? 'is-blocked' : ''}`} onClick={() => onOpen(task.id)}>
        <span className="pj-task-row-title"><strong title={task.title}>{task.title}</strong><span className="pj-inline">{task.priority && task.priority !== 'normale' && <Priority value={task.priority}/>}{task.blocked_reason && <span className="pj-badge pj-alert">Bloquée</span>}</span></span>
        <span className="pj-task-assignee"><Avatar member={task.assignee}/><span>{personName(task.assignee)}</span></span>
        <span className={`pj-deadline ${isLate(task) ? 'is-late' : ''}`}>{isLate(task) && <Clock3 size={13}/>} {dateLabel(task.due_date)}</span>
        <span className={`pj-badge pj-task-${task.status}`}>{TASK_STATUS[task.status]}</span><ArrowUpRight size={16} aria-hidden="true"/>
      </button>
    </li>)}</ul>
    <Pagination page={page} pageSize={8} total={tasks.length} onChange={setPage} label="tâches du projet"/>
  </div>;
}
