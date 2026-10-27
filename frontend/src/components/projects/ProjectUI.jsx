import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { ArrowLeft, ArrowRight, CalendarDays, ChevronLeft, ChevronRight, X } from 'lucide-react';
import { personName, PRIORITY } from './projectUtils';
import '../../Casier.css';
import '../../Projects.css';
export function ProjectPage({
  title,
  intro,
  children,
  actions,
  back = false
}) {
  useEffect(() => {
    document.body.classList.add('projects-no-nav');
    return () => document.body.classList.remove('projects-no-nav');
  }, []);
  return <section className="cz-page pj-page"><header className="cz-header"><div className="cz-header-copy"><p className="cz-eyebrow">ESPACE ANIMATEUR · ATELIER DES PROJETS</p><h1>{title}</h1><p className="cz-intro">{intro}</p></div><div className="cz-header-actions">{back && <Link className="pj-btn" to="/animateur/projects"><ArrowLeft size={16} /> Projets</Link>}<Link className="pj-btn" to="/animateur/calendrier"><CalendarDays size={16} /> Calendrier</Link><Link className="cz-home" to="/">Accueil <ArrowRight size={17} /></Link>{actions}</div></header>{children}</section>;
}
export function Modal({
  title,
  children,
  onClose,
  busy = false
}) {
  const root = useRef(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    root.current?.querySelector('input,textarea,select,button')?.focus();
    return () => {
      document.body.style.overflow = oldOverflow;
      previous?.focus?.();
    };
  }, []);
  return createPortal(<div className="pj-overlay cz-dialog-root" onMouseDown={e => {
    if (e.target === e.currentTarget && !busy) close.current();
  }} onKeyDown={e => {
    if (e.key === 'Escape' && !busy) {
      e.stopPropagation();
      close.current();
    }
    if (e.key === 'Tab') {
      const items = [...root.current.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],[tabindex="0"],[contenteditable="true"]')];
      const first = items[0],
        last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last?.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first?.focus();
      }
    }
  }}><div className="pj-modal" role="dialog" aria-modal="true" aria-labelledby="pj-modal-title" ref={root}><header><div><p className="cz-eyebrow">ATELIER DES PROJETS</p><h2 id="pj-modal-title">{title}</h2></div><button className="pj-icon" onClick={onClose} disabled={busy} aria-label="Fermer"><X size={20} /></button></header>{children}</div></div>, document.body);
}
export function Avatar({
  member
}) {
  return <span className="pj-avatar" title={personName(member)}>{member?.avatar_url ? <img src={member.avatar_url} alt="" onError={e => {
      e.currentTarget.style.display = 'none';
    }} /> : null}<span>{personName(member).slice(0, 2).toUpperCase()}</span></span>;
}
export function Priority({
  value = 'normale'
}) {
  return <span className={`pj-badge pj-priority-${value}`}>Priorité {PRIORITY[value]?.toLowerCase()}</span>;
}
export function Empty({
  title,
  children
}) {
  return <div className="pj-empty"><strong>{title}</strong><p>{children}</p></div>;
}
export function Field({
  label,
  children,
  wide = false
}) {
  return <label className={`pj-field ${wide ? 'pj-wide' : ''}`}><span>{label}</span>{children}</label>;
}
export function Panel({
  title,
  intro,
  actions,
  children,
  className = ''
}) {
  return <section className={`pj-panel ${className}`}><header className="pj-panel-head"><div><h2>{title}</h2>{intro && <p>{intro}</p>}</div>{actions}</header><div className="pj-panel-body">{children}</div></section>;
}


export function usePage(items, pageSize, resetKey) {
  const [requestedPage, setPage] = useState(1);
  useEffect(() => { setPage(1); }, [resetKey]);
  const page = Math.min(requestedPage, Math.max(1, Math.ceil(items.length / pageSize)));
  return { page, setPage, items: items.slice((page - 1) * pageSize, page * pageSize) };
}

export function Pagination({ page, pageSize, total, onChange, label }) {
  if (!total) return null;
  const pages = Math.ceil(total / pageSize);
  return <nav className="pj-pagination" aria-label={`Pagination des ${label}`}>
    <span role="status">{(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} sur {total} {label}</span>
    {pages > 1 && <div><button className="pj-icon" onClick={() => onChange(page - 1)} disabled={page <= 1} aria-label={`Page précédente des ${label}`}><ChevronLeft size={17}/></button><span>{page} / {pages}</span><button className="pj-icon" onClick={() => onChange(page + 1)} disabled={page >= pages} aria-label={`Page suivante des ${label}`}><ChevronRight size={17}/></button></div>}
  </nav>;
}
