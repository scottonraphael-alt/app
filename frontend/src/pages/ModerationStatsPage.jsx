import "../Casier.css";

import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";

import { errorMessage } from "../components/casier/casierApi";
import { fetchModerationStats } from "../components/casier/casierBulkApi";
import { SANCTION_TYPES } from "../components/casier/casierConstants";
import { plural } from "../components/casier/formatters";

const iso = (date) => date.toISOString().slice(0, 10);
const daysAgo = (n) => iso(new Date(Date.now() - n * 86400000));
const PRESETS = [
  { label: "7 jours", days: 6 },
  { label: "30 jours", days: 29 },
  { label: "90 jours", days: 89 },
];

function typeLabel(value) {
  const found = Array.isArray(SANCTION_TYPES) ? SANCTION_TYPES.find((t) => t.value === value) : null;
  return found?.label || value;
}

export default function ModerationStatsPage() {
  const [range, setRange] = useState({ start: daysAgo(29), end: daysAgo(0) });

  useEffect(() => {
    document.body.classList.add("casier-no-nav");
    return () => document.body.classList.remove("casier-no-nav");
  }, []);

  const query = useQuery({
    queryKey: ["moderation-stats", range],
    queryFn: () => fetchModerationStats(range),
    retry: false,
  });
  const data = query.data;
  const maxType = useMemo(() => Math.max(1, ...(data?.by_type || []).map((t) => t.count)), [data]);
  const maxMod = useMemo(() => Math.max(1, ...(data?.by_moderator || []).map((m) => m.total)), [data]);
  const maxDay = useMemo(() => Math.max(1, ...(data?.by_day || []).map((d) => d.count)), [data]);
  const types = (data?.by_type || []).map((t) => t.type);

  return (
    <section className="cz-page" data-testid="moderation-stats-page">
      <header className="cz-header">
        <div className="cz-header-copy">
          <p className="cz-eyebrow">ESPACE RESPONSABLE · MODÉRATION</p>
          <h1>Statistiques de modération</h1>
          <p className="cz-intro">Sanctions par modérateur et par type sur la période. Agrégats uniquement.</p>
        </div>
        <div className="cz-header-actions">
          <Link to="/" className="cz-home">
            Accueil
            <ArrowRight size={18} aria-hidden="true" />
          </Link>
        </div>
      </header>

      <div className="cz-stats-filters" role="group" aria-label="Période">
        {PRESETS.map((p) => (
          <button
            key={p.days}
            type="button"
            className="cz-button cz-button--compact"
            aria-pressed={range.start === daysAgo(p.days) && range.end === daysAgo(0)}
            onClick={() => setRange({ start: daysAgo(p.days), end: daysAgo(0) })}
          >
            {p.label}
          </button>
        ))}
        <label className="cz-stats-date">
          Du
          <input type="date" className="cz-input" value={range.start} max={range.end}
            onChange={(e) => e.target.value && setRange((r) => ({ ...r, start: e.target.value }))} />
        </label>
        <label className="cz-stats-date">
          Au
          <input type="date" className="cz-input" value={range.end} min={range.start}
            onChange={(e) => e.target.value && setRange((r) => ({ ...r, end: e.target.value }))} />
        </label>
      </div>

      {query.isLoading && <p className="cz-meta" role="status">Chargement…</p>}
      {query.isError && (
        <p className="cz-empty cz-empty--error" role="alert">{errorMessage(query.error)}</p>
      )}

      {data && (
        <div className="cz-stats-grid">
          <div className="cz-card cz-stats-kpis">
            <div><strong>{data.total}</strong><span>{plural(data.total, "sanction", "sanctions")}</span></div>
            <div><strong>{data.members_sanctioned}</strong><span>{plural(data.members_sanctioned, "membre concerné", "membres concernés")}</span></div>
            <div><strong>{data.by_moderator.length}</strong><span>{plural(data.by_moderator.length, "modérateur", "modérateurs")}</span></div>
          </div>

          <section className="cz-card" aria-labelledby="st-type">
            <h2 id="st-type">Par type</h2>
            {data.by_type.length === 0 && <p className="cz-meta">Aucune sanction sur la période.</p>}
            <ul className="cz-bars">
              {data.by_type.map((t) => (
                <li key={t.type}>
                  <span className="cz-bars-label">{typeLabel(t.type)}</span>
                  <span className="cz-bars-track" aria-hidden="true"><span style={{ width: `${(t.count / maxType) * 100}%` }} /></span>
                  <span className="cz-bars-value">{t.count}</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="cz-card" aria-labelledby="st-day">
            <h2 id="st-day">Par jour</h2>
            <div className="cz-spark" role="img" aria-label={`Sanctions par jour, maximum ${maxDay}`}>
              {data.by_day.map((d) => (
                <span key={d.date} title={`${d.date} : ${d.count}`} style={{ height: `${Math.max(3, (d.count / maxDay) * 100)}%` }} />
              ))}
            </div>
          </section>

          <section className="cz-card cz-stats-wide" aria-labelledby="st-mod">
            <h2 id="st-mod">Par modérateur</h2>
            <div className="cz-table-wrap">
              <table className="cz-table">
                <thead>
                  <tr>
                    <th scope="col">Modérateur</th>
                    {types.map((t) => <th key={t} scope="col">{typeLabel(t)}</th>)}
                    <th scope="col">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_moderator.map((m) => (
                    <tr key={m.id}>
                      <th scope="row">
                        {m.name}
                        <span className="cz-bars-track" aria-hidden="true"><span style={{ width: `${(m.total / maxMod) * 100}%` }} /></span>
                      </th>
                      {types.map((t) => <td key={t}>{m.by_type[t] || 0}</td>)}
                      <td><strong>{m.total}</strong></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
