import { Children, cloneElement, useEffect, useLayoutEffect, useRef, useState } from 'react';
import './Motion.css';
import {MOTION_EVENT} from '../../hooks/useMotionPreference';

export const motionAllowed = () => document.documentElement.dataset.motion !== 'reduced' && !window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;

export function useReducedMotion() {
  const [reduced, setReduced] = useState(() => !motionAllowed());
  useEffect(() => {
    const query = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    const update = () => setReduced(!motionAllowed());
    update();
    window.addEventListener(MOTION_EVENT, update);
    query?.addEventListener?.('change', update);
    return () => {query?.removeEventListener?.('change', update);window.removeEventListener(MOTION_EVENT, update);};
  }, []);
  return reduced;
}

export function SuccessCheck({ size = 16 }) {
  return <svg className="iris-success-check" width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="10" cy="10" r="8" />
    <path pathLength="1" d="m6.5 10 2.5 2.5 4.5-5" />
  </svg>;
}

// Keep departing rows inert briefly, then move the surviving rows to their new positions.
export function MotionRows({ children, as: Container = 'tbody', ...props }) {
  const rows = Children.toArray(children);
  const signature = JSON.stringify(rows.map(row => row.key));
  const [snapshot, setSnapshot] = useState({ signature, rows, exits: [] });
  const reduced = useReducedMotion();
  const root = useRef(null);
  const positions = useRef(null);
  if (snapshot.signature !== signature) {
    const keys = new Set(rows.map(row => row.key));
    const exits = reduced ? [] : [
      ...snapshot.exits.filter(item => !keys.has(item.row.key)),
      ...snapshot.rows.flatMap((row, index) => keys.has(row.key) ? [] : [{ row, index }]),
    ];
    setSnapshot({ signature, rows, exits });
  }
  useEffect(() => {
    if (!snapshot.exits.length) return;
    const timer = window.setTimeout(() => setSnapshot(current => ({ ...current, exits: [] })), reduced ? 0 : 180);
    return () => window.clearTimeout(timer);
  }, [snapshot.exits, reduced]);
  useLayoutEffect(() => {
    const next = new Map();
    const animations = [];
    const origin = root.current.getBoundingClientRect().top;
    for (const row of root.current.children) {
      const key = row.dataset.motionKey;
      const top = row.getBoundingClientRect().top - origin;
      next.set(key, top);
      if (!reduced && row.animate && !row.hasAttribute('data-exiting') && positions.current) {
        const old = positions.current.get(key);
        if (old !== undefined && old !== top) {
          animations.push(row.animate([{ transform: `translateY(${old - top}px)` }, { transform: 'translateY(0)' }], { duration: 240, easing: 'cubic-bezier(.2,.8,.2,1)' }));
        } else if (old === undefined) {
          animations.push(row.animate([{ opacity: 0, transform: 'translateY(6px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 220 }));
        }
      }
    }
    positions.current = next;
    return () => animations.forEach(animation => animation.cancel());
  });
  const visible = [...rows];
  snapshot.exits.forEach(({ row, index }) => visible.splice(Math.min(index, visible.length), 0,
    cloneElement(row, { inert: true, 'aria-hidden': true, 'data-exiting': true })));
  return <Container {...props} ref={root}>{visible.map(row => cloneElement(row, { 'data-motion-key': row.key }))}</Container>;
}

export function MotionNav({ children, className = '', as: Container = 'nav', ...props }) {
  const root = useRef(null);
  const marker = useRef(null);
  useLayoutEffect(() => {
    const nav = root.current;
    const move = () => {
      const active = nav.querySelector(':is(a,button)[aria-current="page"],button[aria-pressed="true"],button[aria-selected="true"]');
      if (!active) { marker.current.style.opacity = '0'; return; }
      const bounds = nav.getBoundingClientRect();
      const rect = active.getBoundingClientRect();
      Object.assign(marker.current.style, {
        opacity: '1', width: `${rect.width}px`, height: `${rect.height}px`,
        transform: `translate(${rect.left - bounds.left + nav.scrollLeft}px, ${rect.top - bounds.top + nav.scrollTop}px)`,
      });
    };
    move();
    const resize = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(move);
    resize?.observe(nav);
    nav.querySelectorAll('a,button').forEach(link => resize?.observe(link));
    const changes = new MutationObserver(move);
    changes.observe(nav, { subtree: true, attributes: true, attributeFilter: ['aria-current', 'aria-pressed', 'aria-selected'] });
    return () => { resize?.disconnect(); changes.disconnect(); };
  }, [children]);
  return <Container {...props} ref={root} className={`iris-motion-nav ${className}`}>
    <span ref={marker} className="iris-nav-marker" aria-hidden="true" />{children}
  </Container>;
}

// Measure across the entire board so a card can move between different column containers.
export function MotionBoard({ children, className, revision }) {
  const root = useRef(null);
  const positions = useRef(new Map());
  const reduced = useReducedMotion();

  useLayoutEffect(() => {
    const board = root.current;
    const origin = board.getBoundingClientRect();
    const next = new Map();
    const animations = [];
    let entering = 0;

    for (const card of board.querySelectorAll('[data-motion-card]')) {
      const { left, top } = card.getBoundingClientRect();
      const position = { x: left - origin.left, y: top - origin.top };
      const key = card.dataset.motionCard;
      const old = positions.current.get(key);
      next.set(key, position);
      if (reduced || !card.animate) continue;

      if (old) {
        const dx = old.x - position.x;
        const dy = old.y - position.y;
        if (dx || dy) {
          animations.push(card.animate(
            [{ translate: `${dx}px ${dy}px` }, { translate: '0 0' }],
            { duration: 340, easing: 'cubic-bezier(.22,1,.36,1)' },
          ));
        }
      } else if (entering < 5) {
        animations.push(card.animate(
          [{ opacity: .65, translate: '0 8px' }, { opacity: 1, translate: '0 0' }],
          { duration: 280, delay: entering++ * 34, fill: 'backwards', easing: 'cubic-bezier(.22,1,.36,1)' },
        ));
      }
    }

    positions.current = next;
    return () => animations.forEach(animation => animation.cancel());
  }, [revision, reduced]);

  return <div ref={root} className={className}>{children}</div>;
}

export function useNewMessageMotion(ref, revision, items, visible = true) {
  const seen = useRef(new Set());
  const context = useRef(revision);
  const reduced = useReducedMotion();
  useLayoutEffect(() => {
    const container = ref.current;
    if (!container || !visible) return;
    const messages = [...container.querySelectorAll('[data-message-key]')];
    const sameContext = context.current === revision;
    const animations = [];
    for (const message of messages) {
      const key = message.dataset.messageKey;
      if (sameContext && seen.current.size && !seen.current.has(key) && !reduced && message.animate && animations.length < 5) {
        const offset = message.dataset.messageSide === 'outgoing' ? 10 : -10;
        animations.push(message.animate(
          [{ opacity: .55, translate: `${offset}px 5px` }, { opacity: 1, translate: '0 0' }],
          { duration: 280, delay: animations.length * 30, fill: 'backwards', easing: 'cubic-bezier(.22,1,.36,1)' },
        ));
      }
    }
    // Preserve seen IDs during temporary loading states.
    if (messages.length) seen.current = new Set(messages.map(message => message.dataset.messageKey));
    if (messages.length) context.current = revision;
    return () => animations.forEach(animation => animation.cancel());
  }, [ref, revision, reduced, items, visible]);
}
