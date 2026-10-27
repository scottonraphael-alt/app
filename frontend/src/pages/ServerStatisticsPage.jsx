import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, BarChart3, RefreshCw } from "lucide-react";
import { api, getErrorMessage } from "../api/client";
import "@/ServerStatistics.css";

const INTERNAL = ["1081957992896942166", "1321632937502052424", "1499495158469758976"];
const number = (value) => new Intl.NumberFormat("fr-FR").format(value || 0);
const dateTime = (value) => value ? new Date(value).toLocaleString("fr-FR", { timeZone: "Europe/Paris", dateStyle: "short", timeStyle: "short" }) : "Pas encore disponible";
function todayParis() {
  const parts = new Intl.DateTimeFormat("en", { timeZone: "Europe/Paris", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  const value = (type) => parts.find(part => part.type === type).value;
  return `${value("year")}-${value("month")}-${value("day")}`;
}
function daysBefore(day, count) {
  const stamp = new Date(`${day}T12:00:00Z`);
  stamp.setUTCDate(stamp.getUTCDate() - count);
  return stamp.toISOString().slice(0, 10);
}
function initialExcluded() {
  try {
    const values = JSON.parse(localStorage.getItem("iris.statistics.hiddenCategories") || "[]");
    return Array.isArray(values) ? values.filter(value => typeof value === "string" && /^(\d{1,22}|uncategorized)$/.test(value)).slice(0,100) : [];
  } catch { return []; }
}
function Ranking({ title, items, firstColumn }) {
  return <section className="ss-panel"><h2>{title}</h2>{items.length ? <div className="ss-table-scroll"><table><thead><tr><th scope="col">{firstColumn}</th><th scope="col">Messages</th></tr></thead><tbody>{items.map(item => <tr key={item.id}><td>{item.name}</td><td>{number(item.messages)}</td></tr>)}</tbody></table></div> : <p className="ss-empty">Aucune activité sur cette période avec ces filtres.</p>}</section>;
}

export default function ServerStatisticsPage() {
  const today = todayParis();
  const [start, setStart] = useState(() => daysBefore(today, 6));
  const [end, setEnd] = useState(today);
  const [excluded, setExcluded] = useState(initialExcluded);
  const [version, setVersion] = useState(0);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const excludedKey = excluded.join(",");
  useEffect(() => {
    try { localStorage.setItem("iris.statistics.hiddenCategories", JSON.stringify(excluded)); } catch { /* Préférence facultative. */ }
  }, [excluded]);
  useEffect(() => {
    let controller;
    let active = true;
    const load = async () => {
      controller?.abort();
      controller = new AbortController();
      const current = controller;
      if (!start || !end || start > end || end > today) {
        setLoading(false); setError("Choisissez une période valide, jusqu’à aujourd’hui."); return;
      }
      setLoading(true);
      setError("");
      try {
        const response = await api.get("/responsable/statistics", { params: { start, end, exclude_categories: excludedKey }, signal: current.signal });
        if (active && !current.signal.aborted) setData(response.data);
      } catch (requestError) {
        if (active && !current.signal.aborted) setError(getErrorMessage(requestError));
      } finally {
        if (active && !current.signal.aborted) setLoading(false);
      }
    };
    load();
    const interval = window.setInterval(load, 60000);
    return () => { active = false; controller?.abort(); window.clearInterval(interval); };
  }, [start, end, excludedKey, version, today]);
  const preset = (period) => { setEnd(today); setStart(period === "year" ? `${today.slice(0,4)}-01-01` : daysBefore(today, Number(period)-1)); };
  const toggleCategory = (id) => setExcluded(current => current.includes(id) ? current.filter(value => value !== id) : [...current, id]);
  const collection = data?.collection;
  const status = !collection?.enabled ? "Collecte désactivée" : collection.connected ? "Bot connecté" : "Bot hors ligne ou en reconnexion";

  return <main className="ss-page">
    <header className="ss-header"><div><p className="ss-eyebrow">ESPACE RESPONSABLE · ACTIVITÉ DU SERVEUR</p><h1>Statistiques du serveur</h1><p>Participation et activité des salons · Heure de Paris</p></div><nav aria-label="Actions de la page"><Link className="ss-button" to="/">Accueil <ArrowRight size={16} /></Link><button className="ss-button" onClick={() => setVersion(value => value+1)} disabled={loading}><RefreshCw size={16} /> Actualiser</button></nav></header>
    <section className="ss-filters" aria-label="Filtres statistiques"><div className="ss-periods" aria-label="Périodes rapides">{[["1","Aujourd’hui"],["7","7 jours"],["30","30 jours"],["year","Cette année"]].map(([value,label]) => <button type="button" className="ss-button" key={value} onClick={() => preset(value)}>{label}</button>)}</div><div className="ss-dates"><label>Du<input type="date" value={start} max={end || today} onChange={event => setStart(event.target.value)} /></label><label>Au<input type="date" value={end} min={start} max={today} onChange={event => setEnd(event.target.value)} /></label></div>
      <details className="ss-categories"><summary>Catégories affichées{excluded.length ? ` · ${excluded.length} masquée(s)` : " · Toutes"}</summary><div className="ss-category-actions"><button className="ss-button" onClick={() => setExcluded([])}>Tout afficher</button><button className="ss-button" onClick={() => setExcluded(current => [...new Set([...current, ...INTERNAL])])}>Masquer contact staff, staff et soutien</button></div><div className="ss-category-options">{(data?.categories || []).map(category => <label key={category.id}><input type="checkbox" checked={!excluded.includes(category.id)} onChange={() => toggleCategory(category.id)} />{category.name}{category.internal && <small>Espace interne</small>}</label>)}</div><p>Ces filtres modifient tous les compteurs affichés. La collecte conserve les données de toutes les catégories.</p></details>
    </section>
    {error && <div className="ss-notice ss-notice-error" role="alert">{error} <button className="ss-button" onClick={() => setVersion(value => value+1)}>Réessayer</button></div>}
    {loading && <p className="ss-loading" role="status">Actualisation des statistiques…</p>}
    {data && <div aria-busy={loading} className={loading || error ? "ss-results is-stale" : "ss-results"}>
      <section className="ss-collection" aria-label="État de la collecte"><div><span className={`ss-dot ${collection.connected && collection.enabled ? "is-live" : ""}`} /> <strong>{status}</strong><p>Données disponibles depuis le {dateTime(collection.started_at)} · Collecte à partir de l’activation, sans récupération du passé.</p></div><div><span>Dernier signal : {dateTime(collection.last_seen_at)}</span><span>Dernier calcul : {dateTime(collection.last_projection_at)}</span><span>{number(collection.pending_messages)} message(s) en attente de calcul</span></div></section>
      {(collection.last_error || collection.last_ingest_error_at) && <p className="ss-notice ss-notice-error" role="alert">{collection.last_error || `Une interruption de collecte a été détectée le ${dateTime(collection.last_ingest_error_at)}. Les chiffres peuvent être incomplets.`}</p>}
      <section className="ss-kpis" aria-label="Indicateurs de la période">{[["Messages",data.totals.messages],["Membres actifs",data.totals.active_members],["Salons actifs",data.totals.active_channels],["Pièces jointes",data.totals.attachments]].map(([label,value]) => <article key={label}><span>{label}</span><strong>{number(value)}</strong><small>{label === "Membres actifs" ? "Au moins un message sur la période" : "Sur la période et les catégories affichées"}</small></article>)}</section>
      {!data.totals.messages && <div className="ss-notice"><BarChart3 size={20} /><p>Les premiers chiffres apparaîtront après de nouveaux messages humains dans les catégories affichées.</p></div>}
      <div className="ss-grid"><Ranking title="Messages par jour" firstColumn="Jour · Paris" items={data.daily.map(row => ({id:row.day,name:row.day.split("-").reverse().join("/"),messages:row.messages}))} /><Ranking title="Salons les plus actifs · Top 20" firstColumn="Salon" items={data.channels} /><Ranking title="Messages par membre · Top 20" firstColumn="Membre" items={data.members} /><Ranking title="Activité par catégorie" firstColumn="Catégorie" items={data.category_totals} /></div>
      {collection.sessions.length > 0 && <section className="ss-panel"><h2>Connexions récentes du bot</h2><p className="ss-caption">Une interruption de collecte peut expliquer une baisse des chiffres. Un arrêt brutal n’est détecté qu’après l’absence de signal du bot.</p><div className="ss-table-scroll"><table><thead><tr><th scope="col">Connecté depuis</th><th scope="col">Dernier signal</th><th scope="col">Déconnexion</th></tr></thead><tbody>{collection.sessions.map((session,index) => <tr key={`${session.started_at}-${index}`}><td>{dateTime(session.started_at)}</td><td>{dateTime(session.last_seen_at)}</td><td>{session.ended_at ? dateTime(session.ended_at) : index === 0 && collection.connected ? "En cours" : "Fin non confirmée"}</td></tr>)}</tbody></table></div></section>}
      <p className="ss-footnote">Messages humains uniquement, pièces jointes comprises. Bots, webhooks et messages système exclus. Aucun texte de message n’est conservé pour les statistiques. Registre technique : {collection.registry_days} jours ; les corrections de messages plus anciens ne sont pas répercutées. Les graphiques interactifs seront ajoutés au bloc 2.</p>
    </div>}
  </main>;
}
