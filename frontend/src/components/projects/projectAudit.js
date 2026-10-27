import { useEffect } from 'react';
import { api } from '../../api/client';

// Interface intent is distinct from successful writes confirmed by server logs.
// Record committed field changes, not individual keystrokes or rich-text contents.
export function useProjectAudit(projectId, page) {
  useEffect(() => {
    const send = (kind, label, extra = {}) => {
      api.post('/animateur/projects/workspace/events', {
        kind, page, project_id: projectId || null,
        label: String(label || 'Action dans les projets').replace(/\s+/g, ' ').trim().slice(0,180), ...extra,
      }).catch(() => undefined);
    };
    const scoped = target => target instanceof Element && target.closest('.pj-page,.pj-modal,.pj-overlay');
    const label = el => el.getAttribute('aria-label') || el.getAttribute('title') || el.closest('label')?.querySelector('span')?.textContent || el.textContent || el.tagName;
    const click = e => {
      if (!scoped(e.target)) return;
      const button = e.target.closest('button,a,summary,[role="button"]');
      if (button && !button.disabled) send('clicked', label(button));
    };
    const change = e => {
      if (!scoped(e.target) || !e.target.matches('input,select,textarea')) return;
      const el=e.target;
      if (el.type === 'password') return;
      const extra = el.matches('select,input[type=date],input[type=checkbox],input[type=radio]')
        ? {value: el.type === 'checkbox' ? (el.checked ? 'Activé' : 'Désactivé') : el.tagName === 'SELECT' ? el.selectedOptions[0]?.textContent.slice(0,100) || '' : el.value.slice(0,100)}
        : {length: el.type === 'file' ? el.files.length : el.value.length};
      send('changed', label(el), extra);
    };
    const submit = e => { if (scoped(e.target)) send('submitted', e.target.getAttribute('aria-label') || e.target.querySelector('button[type=submit],button:not([type])')?.textContent || 'Enregistrer le formulaire'); };
    const toggle = e => { if (scoped(e.target) && e.target.matches('details')) send('toggled', e.target.querySelector('summary')?.textContent, {value:e.target.open?'ouvert':'fermé'}); };
    const blur = e => { if (scoped(e.target) && e.target.matches('[contenteditable="true"]')) send('edited', 'Éditeur du projet', {length:Math.min(e.target.textContent.length,10000000)}); };
    const shortcut = e => {
      if (scoped(e.target) && (e.key === 'Escape' || ((e.ctrlKey || e.metaKey) && ['b','i','u','z','y'].includes(e.key.toLowerCase())))) send('shortcut', e.key === 'Escape' ? 'Fermer le dialogue (Échap)' : `Éditeur : ${e.key.toUpperCase()}`);
    };
    const backdrop = e => { if (e.target instanceof Element && e.target.matches('.pj-overlay')) send('clicked', 'Clic en dehors de la fenêtre du dialogue'); };
    const events = {click,change,submit,toggle,focusout:blur,keydown:shortcut,pointerdown:backdrop};
    Object.entries(events).forEach(([name,fn]) => document.addEventListener(name,fn,true));
    return () => Object.entries(events).forEach(([name,fn]) => document.removeEventListener(name,fn,true));
  }, [projectId,page]);
}

export function projectConfirm(message) {
  const confirmed=window.confirm(message);
  const page=document.querySelector('.pj-page');
  api.post('/animateur/projects/workspace/events', {
    kind:'changed', page:page?.dataset.auditPage || 'project',
    project_id:page?.dataset.projectId || null,
    label:`Confirmation : ${message}`.slice(0,180), value:confirmed?'Confirmée':'Annulée',
  }).catch(()=>undefined);
  return confirmed;
}
