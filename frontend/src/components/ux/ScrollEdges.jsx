import { useLayoutEffect, useRef, useState } from 'react';
import './StateMotion.css';

export function scrollEdges(node) {
  const maxX = Math.max(0, node.scrollWidth - node.clientWidth), maxY = Math.max(0, node.scrollHeight - node.clientHeight);
  const x = Math.max(0, Math.min(maxX, node.scrollLeft)), y = Math.max(0, Math.min(maxY, node.scrollTop));
  return { left: x > 1, right: maxX - x > 1, top: y > 1, bottom: maxY - y > 1 };
}
export default function ScrollEdges({ children, className = '', fill = false, label, ...props }) {
  const root = useRef(null);
  const [edges, setEdges] = useState({});
  useLayoutEffect(() => {
    const node = root.current;
    const update = () => {
      const next = scrollEdges(node);
      setEdges(previous => Object.keys(next).every(key => next[key] === previous[key]) ? previous : next);
    };
    update();
    const resize = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(update);
    const observe = () => { resize?.disconnect(); resize?.observe(node); [...node.children].forEach(child => resize?.observe(child)); update(); };
    observe();
    const mutation = new MutationObserver(observe);
    mutation.observe(node, { childList: true, subtree: true, characterData: true });
    node.addEventListener('scroll', update, { passive: true });
    node.addEventListener('load', update, true);
    window.addEventListener('resize', update);
    return () => { resize?.disconnect(); mutation.disconnect(); node.removeEventListener('scroll', update); node.removeEventListener('load', update, true); window.removeEventListener('resize', update); };
  }, []);
  const horizontal = edges.left || edges.right;
  return <div className={`iris-scroll-frame ${fill ? 'iris-scroll-frame--fill' : ''}`}>
    <div {...props} className={className} ref={root} tabIndex={horizontal ? 0 : undefined} role={label && horizontal ? 'region' : undefined} aria-label={label && horizontal ? label : undefined}>{children}</div>
    {['left', 'right', 'top', 'bottom'].map(edge => <span key={edge} className={`iris-scroll-edge iris-scroll-edge--${edge}`} data-visible={edges[edge] || undefined} aria-hidden="true"/>)}
  </div>;
}
