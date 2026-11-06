import { useLayoutEffect, useRef } from 'react';
import { Check } from 'lucide-react';
import './CaseMotion.css';

const slideDuration = 320;

export function SlidingPanels({ active, children }) {
  const viewport = useRef(null);
  const track = useRef(null);
  const previousIndex = useRef(active);

  useLayoutEffect(() => {
    const container = viewport.current;
    const panel = track.current.children[active];
    let outgoing = track.current.children[previousIndex.current];
    previousIndex.current = active;
    if (outgoing === panel || window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches) {
      outgoing = null;
    }
    const fit = () => {
      if (!container.getClientRects().length) return;
      const height = Math.max(panel.getBoundingClientRect().height, outgoing?.getBoundingClientRect().height ?? 0);
      container.style.setProperty('--case-panel-height', `${height}px`);
    };
    fit();
    // Keep the outgoing card at full height until it has slid out of view.
    const settle = outgoing && window.setTimeout(() => {
      outgoing = null;
      fit();
    }, slideDuration);
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(fit);
    observer?.observe(panel);
    return () => {
      window.clearTimeout(settle);
      observer?.disconnect();
    };
  }, [active]);

  return <div className="case-slide-viewport" ref={viewport} style={{ '--case-slide-duration': `${slideDuration}ms` }}>
    <div className="case-slide-track" ref={track} style={{ '--case-panel-index': active }}>
      {children.map((content, index) => (
        <div className="case-slide-panel" key={index} inert={index !== active} aria-hidden={index !== active}>
          {content}
        </div>
      ))}
    </div>
  </div>;
}

export function CasePanelLoading() {
  return <div className="case-panel-loading" role="status">
    <span>Chargement des dossiers…</span>
    <div className="case-panel-loading-rows" aria-hidden="true">
      {[0, 1, 2].map(row => <div className="case-panel-loading-row" key={row}><i /><i /><i /></div>)}
    </div>
  </div>;
}

export function ActionProgressButton({ busy, pendingLabel = 'Enregistrement…', confirmed, children, className, disabled, ...props }) {
  const complete = !busy && Boolean(confirmed);
  return <button {...props} className={`${className} case-action-progress`}
    disabled={disabled || busy} aria-busy={Boolean(busy)} data-confirmed={complete || undefined}>
    <span>{busy ? pendingLabel : complete ? <><Check size={15} aria-hidden="true" /> Enregistré</> : children}</span>
  </button>;
}
