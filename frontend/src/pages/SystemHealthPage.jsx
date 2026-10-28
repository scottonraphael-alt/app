import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, RefreshCw } from "lucide-react";

import { api, getErrorMessage } from "../api/client";
import "../components/responsable/Responsable.css";

const TZ = "Europe/Paris";
const fmt = (iso) =>
  iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "medium", timeZone: TZ }) : "—";
const STATUS_LABELS = {
  pending: "En attente",
  sending: "En cours d’envoi",
  sent: "Envoyés",
  failed: "En échec",
  skipped: "Ignorés",
  cancelled: "Annulés",
};

export default function SystemHealthPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    document.body.classList.add("rs-no-nav");
    return () => document.body.classList.remove("rs-no-nav");
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await api.get("/system-health");
      setData(response.data);
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const reminders = data?.reminders;

  return (
    <section className="rs-page" data-testid="system-health-page">
      <header className="rs-header">
        <div className="rs-header-copy">
          <p className="rs-eyebrow">ESPACE RESPONSABLE · SYSTÈME</p>
          <h1>Santé du système</h1>
          <p className="rs-intro">
            État des tâches de fond, de la base de données et de la file des rappels.
            {data && (
              <>
                {" "}
                <span className={`rs-pill ${data.status === "ok" ? "rs-pill-ok" : "rs-pill-warn"}`}>
                  {data.status === "ok" ? "Tout est en ordre" : "À surveiller"}
                </span>
              </>
            )}
          </p>
        </div>
        <div className="rs-actions">
          <button type="button" className="rs-btn" onClick={load} disabled={loading}>
            <RefreshCw size={16} aria-hidden="true" />
            {loading ? "Actualisation…" : "Actualiser"}
          </button>
          <Link to="/" className="rs-home">
            Accueil
            <ArrowRight size={18} aria-hidden="true" />
          </Link>
        </div>
      </header>

      {error && <p className="rs-error" role="alert">{error}</p>}
      {loading && !data && <p className="rs-muted" role="status">Chargement…</p>}

      {data && (
        <div className="rs-grid">
          <article className="rs-card">
            <h2>
              Base de données
              <span className={`rs-pill ${data.mongo.ok ? "rs-pill-ok" : "rs-pill-bad"}`}>
                {data.mongo.ok ? "Connectée" : "Injoignable"}
              </span>
            </h2>
            <p className="rs-card-hint">
              {data.mongo.ok ? `Latence : ${data.mongo.latency_ms} ms.` : `Erreur : ${data.mongo.error || "inconnue"}.`}
            </p>
            <p className="rs-muted">Vérifié le {fmt(data.checked_at)}</p>
          </article>

          <article className="rs-card">
            <h2>File des rappels</h2>
            {!reminders.available ? (
              <p className="rs-error">File illisible.</p>
            ) : (
              <>
                <div className="rs-stats">
                  {Object.entries(STATUS_LABELS).map(([key, label]) => (
                    <div className="rs-stat" key={key}>
                      <strong>{reminders.counts[key] ?? 0}</strong>
                      <span>{label}</span>
                    </div>
                  ))}
                </div>
                <p className="rs-muted">
                  {reminders.overdue > 0 ? (
                    <span className="rs-pill rs-pill-warn">{reminders.overdue} en retard</span>
                  ) : (
                    "Aucun retard."
                  )}{" "}
                  Plus ancien rappel en attente : {fmt(reminders.oldest_due_at)}
                </p>
                {reminders.recent_failures.length > 0 && (
                  <ul className="rs-list" aria-label="Derniers échecs de rappels">
                    {reminders.recent_failures.map((item, index) => (
                      <li key={`${item.at}-${index}`}>
                        <div className="rs-list-head">
                          <strong>{item.target_type || "rappel"} {item.offset}</strong>
                          <span className="rs-muted">{fmt(item.at)}</span>
                        </div>
                        <span className="rs-code">{item.error || "Erreur inconnue"}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </article>

          <article className="rs-card rs-card-wide">
            <h2>Tâches de fond</h2>
            <p className="rs-card-hint">
              Mises à jour par les boucles qui enregistrent leurs passages. Une tâche absente n’a pas encore tourné depuis le démarrage.
            </p>
            {data.tasks.length === 0 ? (
              <p className="rs-muted">Aucun passage enregistré pour le moment.</p>
            ) : (
              <div className="rs-table-wrap">
                <table className="rs-table">
                  <thead>
                    <tr>
                      <th scope="col">Tâche</th>
                      <th scope="col">État</th>
                      <th scope="col">Dernière exécution</th>
                      <th scope="col">Durée</th>
                      <th scope="col">Passages</th>
                      <th scope="col">Erreurs récentes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.tasks.map((task) => (
                      <tr key={task.name}>
                        <th scope="row" className="rs-code">{task.name}</th>
                        <td>
                          <span className={`rs-pill ${task.last_ok === false ? "rs-pill-bad" : "rs-pill-ok"}`}>
                            {task.last_ok === false ? "Échec" : "OK"}
                          </span>
                        </td>
                        <td>{fmt(task.last_run_at)}</td>
                        <td>{task.last_duration_ms != null ? `${task.last_duration_ms} ms` : "—"}</td>
                        <td>{task.runs} ({task.failures} en échec)</td>
                        <td>
                          {task.recent_errors.length === 0
                            ? "—"
                            : task.recent_errors.map((err, i) => (
                                <div key={i} className="rs-code">{fmt(err.at)} · {err.message}</div>
                              ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </article>
        </div>
      )}
    </section>
  );
}
