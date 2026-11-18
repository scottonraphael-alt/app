import { createContext, useCallback, useContext, useLayoutEffect, useRef, useState } from 'react';
import { useLocation, useNavigationType } from 'react-router-dom';

const PageMemory = createContext(null);

// Memory belongs to the mounted account shell, never to localStorage or a module singleton.
export function PageMemoryProvider({ children }) {
  const memory = useRef({ filters: new Map(), scroll: new Map() });
  useLayoutEffect(() => {
    const previous = window.history.scrollRestoration;
    window.history.scrollRestoration = "manual";
    return () => { window.history.scrollRestoration = previous; };
  }, []);
  return <PageMemory.Provider value={memory.current}>{children}</PageMemory.Provider>;
}

export function usePageMemoryState(key, initial) {
  const memory = useContext(PageMemory);
  const [value, setValue] = useState(() => key && memory?.filters.has(key) ? memory.filters.get(key) : initial);
  const update = useCallback(next => {
    setValue(previous => {
      const resolved = typeof next === 'function' ? next(previous) : next;
      if (memory && key) {
        memory.filters.set(key, resolved);
        if (memory.filters.size > 80) memory.filters.delete(memory.filters.keys().next().value);
      }
      return resolved;
    });
  }, [key, memory]);
  return [value, update];
}

// A POP restores the saved position once asynchronously loaded content is tall enough.
// User scrolling immediately takes precedence; no content or search terms are persisted.
export function usePageReturnPosition() {
  const memory = useContext(PageMemory);
  const location = useLocation();
  const navigation = useNavigationType();
  const previous = useRef(null);
  useLayoutEffect(() => {
    if (!memory) return undefined;
    const changedPage = previous.current !== location.pathname;
    previous.current = location.pathname;
    const saved = memory.scroll.get(location.key);
    let restoring = navigation === 'POP' && Boolean(saved);
    let timer;
    let highlightTimer;
    let highlighted;
    let selectedHref = saved?.href || null;
    let observer;
    const stopRestoring = () => {
      restoring = false;
      observer?.disconnect();
      window.clearTimeout(timer);
    };
    const restore = () => {
      if (!restoring) return;
      window.scrollTo({ top: saved.y, left: saved.x, behavior: 'instant' });
      const target = saved.href ? [...document.querySelectorAll('.app-main a[href]')].find(link => link.getAttribute('href') === saved.href) : null;
      if (document.documentElement.scrollHeight - window.innerHeight >= saved.y && (!saved.href || target)) {
        if (target) {
          target.focus({ preventScroll: true });
          target.classList.add('iris-return-target');
          highlighted = target;
          highlightTimer = window.setTimeout(() => target.classList.remove('iris-return-target'), 1600);
        }
        stopRestoring();
      }
    };
    if (restoring) {
      observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(restore);
      observer?.observe(document.body);
      timer = window.setTimeout(stopRestoring, 5000);
      restore();
    } else if (changedPage && !location.hash) {
      window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
    }
    const cancel = event => {
      if (event.type !== 'keydown' || ['ArrowDown', 'ArrowUp', 'PageDown', 'PageUp', 'Home', 'End', ' '].includes(event.key)) stopRestoring();
    };
    const remember = () => {
      if (!restoring) {
        memory.scroll.set(location.key, { x: window.scrollX, y: window.scrollY, href: selectedHref });
        if (memory.scroll.size > 80) memory.scroll.delete(memory.scroll.keys().next().value);
      }
    };
    const select = event => {
      const link = event.target.closest?.('a.pj-project-row,a.pj-personal-task,a.rl-card,a.tl-row,a.tar-ticket,a.cw-case-link,a.cw-card-link,a.cz-card-link');
      if (link && !event.metaKey && !event.ctrlKey && !event.shiftKey && event.button === 0) {
        selectedHref = link.getAttribute('href');
        remember();
      }
    };
    if (!restoring) remember();
    document.addEventListener('click', select, true);
    window.addEventListener('scroll', remember, { passive: true });
    window.addEventListener('pointerdown', cancel, { passive: true });
    window.addEventListener('wheel', cancel, { passive: true });
    window.addEventListener('touchstart', cancel, { passive: true });
    window.addEventListener('keydown', cancel);
    return () => {
      stopRestoring();
      window.clearTimeout(highlightTimer);
      highlighted?.classList.remove('iris-return-target');
      document.removeEventListener('click', select, true);
      window.removeEventListener('scroll', remember);
      window.removeEventListener('pointerdown', cancel);
      window.removeEventListener('wheel', cancel);
      window.removeEventListener('touchstart', cancel);
      window.removeEventListener('keydown', cancel);
    };
  }, [location.key, location.pathname, location.hash, memory, navigation]);
}
