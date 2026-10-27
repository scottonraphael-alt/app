import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, BarChart3, RefreshCw } from "lucide-react";
import { api, getErrorMessage } from "../api/client";
import InteractionStatistics from "../components/statistics/InteractionStatistics";
import MemberStatistics from "../components/statistics/MemberStatistics";
import StatisticsCharts from "../components/statistics/StatisticsCharts";
import { coverageLabel, weekdays } from "../components/statistics/chartOptions";
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
function Delta({ metric, comparison }) {
  if (!comparison) return null;
  const change=comparison.changes[metric];
  const previous=comparison.previous[metric] || 0;
  const current=comparison.current[metric] || 0;
  const label=!comparison.reliable ? "Comparaison : collecte incomplète" : previous===0 ? current===0 ? "Stable · base 0" : "Nouvelle activité · base 0" : `${change > 0 ? "+" : ""}${change} % vs période précédente`;
  return <span className={`ss-delta ${change > 0 ? "is-up" : change < 0 ? "is-down" : ""}`} title={`Sur la fenêtre de comparaison : ${number(current)} contre ${number(previous)}.`}>{label}</span>;
}

export default function ServerStatisticsPage() {
  const today = todayParis();
  const [start, setStart] = useState(() => daysBefore(today, 6));
  const [end, setEnd] = useState(today);
  const [excluded, setExcluded] = useState(initialExcluded);
  const [version, setVersion] = useState(0);
  const [view, setView] = useState("activity");
  const [granularity, setGranularity] = useState("day");
  const [compare, setCompare] = useState(true);
  const [category, setCategory] = useState("");
  const [channel, setChannel] = useState("");
  const [member, setMember] = useState("");
  const [weekday, setWeekday] = useState("");
  const [hour, setHour] = useState("");
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
        const response = await api.get("/responsable/statistics", { params: { start, end, exclude_categories: excludedKey, granularity, compare, include_members:view==="members", include_interactions:view==="interactions", category_id:category || undefined, channel_id:channel || undefined, member_id:member || undefined, weekday:weekday === "" ? undefined : Number(weekday), hour:hour === "" ? undefined : Number(hour) }, signal: current.signal });
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
  }, [start, end, excludedKey, version, today, granularity, compare, category, channel, member, weekday, hour, view]);
  const preset = (period) => { setEnd(today); setStart(period === "year" ? `${today.slice(0,4)}-01-01` : daysBefore(today, Number(period)-1)); };
  const toggleCategory = (id) => setExcluded(current => current.includes(id) ? current.filter(value => value !== id) : [...current, id]);
  const pickCategory = (id) => { setCategory(id); setChannel(""); };
  const explorePeriod = (row) => { setStart(row.from); setEnd(row.to); setGranularity(granularity==="year" ? "month" : granularity==="month" || granularity==="week" ? "day" : "hour"); };
  const resetDetails = () => { setCategory(""); setChannel(""); setMember(""); setWeekday(""); setHour(""); };
  const comparison = data?.charts?.comparison;
  const collection = data?.collection;
  const status = !collection?.enabled ? "Collecte désactivée" : collection.connected ? "Bot connecté" : "Bot hors ligne ou en reconnexion";

  return <main className="ss-page">
    <header className="ss-header"><div><p className="ss-eyebrow">ESPACE RESPONSABLE · ACTIVITÉ DU SERVEUR</p><h1>Statistiques du serveur</h1><p>Participation et activité des salons · Heure de Paris</p></div><nav aria-label="Actions de la page"><Link className="ss-button" to="/">Accueil <ArrowRight size={16} /></Link><button className="ss-button" onClick={() => setVersion(value => value+1)} disabled={loading}><RefreshCw size={16} /> Actualiser</button></nav></header>
    <nav className="ss-view-tabs" aria-label="Vue des statistiques"><button className="ss-button" aria-pressed={view==="activity"} onClick={()=>setView("activity")}>Activité du serveur</button><button className="ss-button" aria-pressed={view==="members"} onClick={()=>setView("members")}>Membres et fidélisation</button><button className="ss-button" aria-pressed={view==="interactions"} onClick={()=>setView("interactions")}>Interactions et équilibre</button></nav>
    <section className="ss-filters" aria-label="Filtres statistiques"><div className="ss-periods" aria-label="Périodes rapides">{[["1","Aujourd’hui"],["7","7 jours"],["30","30 jours"],["year","Cette année"]].map(([value,label]) => <button type="button" className="ss-button" key={value} onClick={() => preset(value)}>{label}</button>)}</div><div className="ss-dates"><label>Du<input type="date" value={start} max={end || today} onChange={event => setStart(event.target.value)} /></label><label>Au<input type="date" value={end} min={start} max={today} onChange={event => setEnd(event.target.value)} /></label></div>
      <details className="ss-categories"><summary>Catégories affichées{excluded.length ? ` · ${excluded.length} masquée(s)` : " · Toutes"}</summary><div className="ss-category-actions"><button className="ss-button" onClick={() => setExcluded([])}>Tout afficher</button><button className="ss-button" onClick={() => setExcluded(current => [...new Set([...current, ...INTERNAL])])}>Masquer contact staff, staff et soutien</button></div><div className="ss-category-options">{(data?.categories || []).map(category => <label key={category.id}><input type="checkbox" checked={!excluded.includes(category.id)} onChange={() => toggleCategory(category.id)} />{category.name}{category.internal && <small>Espace interne</small>}</label>)}</div><p>Ces filtres modifient tous les compteurs affichés. La collecte conserve les données de toutes les catégories.</p></details>
      <div className="ss-chart-controls">
        <label>Regrouper par<select value={granularity} onChange={event=>setGranularity(event.target.value)} aria-label="Regrouper les messages">{[["hour","Heure"],["day","Jour"],["week","Semaine"],["month","Mois"],["year","Année"]].map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
        <label>Catégorie<select value={category} onChange={event=>pickCategory(event.target.value)} aria-label="Filtrer une catégorie"><option value="">Toutes les catégories affichées</option>{(data?.categories || []).filter(row=>!excluded.includes(row.id)).map(row=><option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
        <label>Salon<select value={channel} onChange={event=>setChannel(event.target.value)} aria-label="Filtrer un salon"><option value="">Tous les salons</option>{(data?.available_channels || []).filter(row=>(!category || row.category_id===category) && !excluded.includes(row.category_id)).map(row=><option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
        <label className="ss-compare-toggle"><input type="checkbox" checked={compare} onChange={event=>setCompare(event.target.checked)} /> Comparer à la période précédente</label>
      </div>
      {(category || channel || member || weekday!=="" || hour!=="") && <div className="ss-active-filters" aria-label="Filtres actifs">{category && <button className="ss-button" onClick={()=>setCategory("")}>Catégorie : {data?.categories?.find(row=>row.id===category)?.name || category} ×</button>}{channel && <button className="ss-button" onClick={()=>setChannel("")}>Salon : {data?.available_channels?.find(row=>row.id===channel)?.name || channel} ×</button>}{member && <button className="ss-button" onClick={()=>setMember("")}>Membre : {data?.selected_member?.name || member} ×</button>}{weekday!=="" && <button className="ss-button" onClick={()=>setWeekday("")}>{weekdays[Number(weekday)]} ×</button>}{hour!=="" && <button className="ss-button" onClick={()=>setHour("")}>{hour} h ×</button>}<button className="ss-button" onClick={resetDetails}>Retirer les filtres d’exploration</button></div>}
    </section>
    {error && <div className="ss-notice ss-notice-error" role="alert">{error} <button className="ss-button" onClick={() => setVersion(value => value+1)}>Réessayer</button></div>}
    {loading && <p className="ss-loading" role="status">Actualisation des statistiques…</p>}
    {data && <div aria-busy={loading} className={loading || error ? "ss-results is-stale" : "ss-results"}>
      <section className="ss-collection" aria-label="État de la collecte"><div><span className={`ss-dot ${collection.connected && collection.enabled ? "is-live" : ""}`} /> <strong>{status}</strong><p>Données disponibles depuis le {dateTime(collection.started_at)} · Collecte à partir de l’activation, sans récupération du passé.</p></div><div><span>Dernier signal : {dateTime(collection.last_seen_at)}</span><span>Dernier calcul : {dateTime(collection.last_projection_at)}</span><span>{number(collection.pending_messages)} message(s) en attente de calcul</span></div></section>
      {(collection.last_error || collection.last_ingest_error_at) && <p className="ss-notice ss-notice-error" role="alert">{collection.last_error || `Une interruption de collecte a été détectée le ${dateTime(collection.last_ingest_error_at)}. Les chiffres peuvent être incomplets.`}</p>}
      {view==="activity" && <>
      {data.charts && <div className={`ss-coverage ${data.charts.coverage.ratio < .98 ? "is-partial" : ""}`}><strong>Connexion du bot couverte : {coverageLabel(data.charts.coverage.ratio)}</strong><span>{number(data.charts.coverage.observed_hours)} h observées sur {number(data.charts.coverage.possible_hours)} h. Les périodes sans collecte ne sont pas assimilées à une activité nulle.</span></div>}
      <section className="ss-kpis" aria-label="Indicateurs de la période">{[["Messages","messages"],["Membres actifs","active_members"],["Salons actifs","active_channels"],["Pièces jointes","attachments"]].map(([label,key]) => <article key={key}><span>{label}</span><strong>{number(data.totals[key])}</strong><Delta metric={key} comparison={comparison} /><small>{key === "active_members" ? "Au moins un message sur la période" : "Sur la période et les catégories affichées"}</small></article>)}</section>
      {comparison && <p className="ss-comparison-caption">Comparaison avec le {comparison.start.split("-").reverse().join("/")} au {comparison.end.split("-").reverse().join("/")}.{comparison.complete_hours_only && <> Les variations portent sur les heures complètes jusqu’au {dateTime(comparison.current_until)} ; les totaux incluent aussi l’heure en cours.</>}{!comparison.reliable && " Les pourcentages sont masqués si la connexion ou les données de collecte sont incomplètes."}</p>}
      {!data.totals.messages && <div className="ss-notice"><BarChart3 size={20} /><p>Aucun message observé pour ces filtres. Vérifiez la couverture de collecte avant de conclure à une absence d’activité.</p></div>}
      <StatisticsCharts data={data} granularity={granularity} onPeriod={explorePeriod} onCategory={pickCategory} onChannel={setChannel} onMember={setMember} onPeak={row=>{ setWeekday(String(row.weekday)); setHour(String(row.hour)); }} onHour={row=>setHour(String(row.hour))} />
      </>}
      {view==="members" && <MemberStatistics metrics={data.member_metrics} />}
      {view==="interactions" && <InteractionStatistics metrics={data.interaction_metrics} onMember={setMember} onCategory={pickCategory} />}
      {collection.sessions.length > 0 && <section className="ss-panel"><h2>Connexions récentes du bot</h2><p className="ss-caption">Une interruption de collecte peut expliquer une baisse des chiffres. Un arrêt brutal n’est détecté qu’après l’absence de signal du bot.</p><div className="ss-table-scroll"><table><thead><tr><th scope="col">Connecté depuis</th><th scope="col">Dernier signal</th><th scope="col">Déconnexion</th></tr></thead><tbody>{collection.sessions.map((session,index) => <tr key={`${session.started_at}-${index}`}><td>{dateTime(session.started_at)}</td><td>{dateTime(session.last_seen_at)}</td><td>{session.ended_at ? dateTime(session.ended_at) : index === 0 && collection.connected ? "En cours" : "Fin non confirmée"}</td></tr>)}</tbody></table></div></section>}
      <p className="ss-footnote">Messages humains uniquement, pièces jointes comprises. Bots, webhooks et messages système exclus. Aucun texte de message n’est conservé pour les statistiques. Registre technique : {collection.registry_days} jours ; les corrections de messages plus anciens ne sont pas répercutées.</p>
    </div>}
  </main>;
}
