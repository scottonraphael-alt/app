import { useEffect } from 'react';
import { api } from '../../api/client';
export default function useAnnouncementAudit(id) {
  useEffect(() => {
    const send = (kind, label, extra = {}) => api.post('/responsable/annonces/events', {
      kind,
      label: String(label || 'Annonce').replace(/\s+/g, ' ').slice(0, 180),
      announcement_id: id,
      ...extra
    }).catch(() => undefined);
    const scoped = target => target instanceof Element && target.closest('.an-page,.an-publish-dialog,.an-dialog');
    const label = el => el.getAttribute('aria-label') || el.closest('label')?.querySelector('span')?.textContent || el.closest('label')?.textContent || el.textContent || el.tagName;
    const click = e => {
      if (scoped(e.target)) {
        const el = e.target.closest('button,a,summary');
        if (el && !el.disabled) send('clicked', label(el));
      }
    };
    const change = e => {
      const el = e.target;
      if (scoped(el) && el.matches('input,select,textarea')) send('changed', el.getAttribute('aria-label') || label(el), el.matches('select,input[type=checkbox]') ? {
        value: el.type === 'checkbox' ? String(el.checked) : String(el.value).slice(0, 100)
      } : {
        length: el.type === 'file' ? el.files.length : el.value.length
      });
    };
    const toggle = e => {
      if (scoped(e.target) && e.target.matches('details')) send('toggled', e.target.querySelector('summary')?.textContent, {
        value: e.target.open ? 'ouvert' : 'fermé'
      });
    };
    document.addEventListener('click', click, true);
    document.addEventListener('change', change, true);
    document.addEventListener('toggle', toggle, true);
    return () => {
      document.removeEventListener('click', click, true);
      document.removeEventListener('change', change, true);
      document.removeEventListener('toggle', toggle, true);
    };
  }, [id]);
}
