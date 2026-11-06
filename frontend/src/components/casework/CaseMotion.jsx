import { useLayoutEffect, useRef } from 'react';
import './CaseMotion.css';

export function SlidingPanels({ active, children }) {
  const viewport = useRef(null);
  const track = useRef(null);

  useLayoutEffect(() => {
    const container = viewport.current;
    const panel = track.current.children[active];
    const fit = () => {
      const height = panel.getBoundingClientRect().height;
      container.style.setProperty('--case-panel-height', `${height}px`);
    };
    fit();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(fit);
    observer.observe(panel);
    return () => observer.disconnect();
  }, [active]);

  return <div className="case-slide-viewport" ref={viewport}>
    <div className="case-slide-track" ref={track} style={{ '--case-panel-index': active }}>
      {children.map((content, index) => (
        <div className="case-slide-panel" key={index} inert={index !== active} aria-hidden={index !== active}>
          {content}
        </div>
      ))}
    </div>
  </div>;
}

export function ActionProgressButton({ busy, pendingLabel = 'Enregistrement…', children, className, disabled, ...props }) {
  return <button {...props} className={`${className} case-action-progress`}
    disabled={disabled || busy} aria-busy={Boolean(busy)}>
    <span>{busy ? pendingLabel : children}</span>
  </button>;
}
