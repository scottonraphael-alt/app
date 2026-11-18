import './Refinements.css';

export default function LoadingSkeleton({ label = 'Chargement…', variant = 'rows', count = 3, ...props }) {
  return <div {...props} className={`iris-loading iris-loading--${variant}`} role="status" aria-label={label}>
    <span className="iris-visually-hidden">{label}</span>
    <div className="iris-loading-shapes" aria-hidden="true">{Array.from({ length: count }, (_, index) => <div className="iris-loading-item" key={index}>
      <span className="iris-loading-icon"/><div><span className="iris-loading-line"/><span className="iris-loading-line iris-loading-line--short"/></div>
    </div>)}</div>
  </div>;
}
