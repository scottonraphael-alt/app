import "./extras.css";

export default function TagFilter({ tags, value, onChange }) {
  if (!tags?.length) return null;
  return (
    <div className="tx-tagfilter" role="group" aria-label="Filtrer par étiquette">
      <span className="tx-label">Étiquette</span>
      <button type="button" className={`tx-chip${!value ? " is-on" : ""}`} aria-pressed={!value} onClick={() => onChange("")}>Toutes</button>
      {tags.map((tag) => (
        <button key={tag.id} type="button" className={`tx-chip tx-c-${tag.color}${value === tag.id ? " is-on" : ""}`}
          aria-pressed={value === tag.id} onClick={() => onChange(value === tag.id ? "" : tag.id)}>{tag.name}</button>
      ))}
    </div>
  );
}
