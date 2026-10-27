import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, BarChart3, RefreshCw, SlidersHorizontal, Users, Network } from "lucide-react";
import { api, getErrorMessage } from "../api/client";
import { MetricCollection } from "../components/statistics/StatisticsReading";
import InteractionStatistics from "../components/statistics/InteractionStatistics";
import MemberStatistics from "../components/statistics/MemberStatistics";
import StatisticsCharts from "../components/statistics/StatisticsCharts";
import { coverageLabel, weekdays } from "../components/statistics/chartOptions";
import "@/Casier.css";
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
    document.body.classList.add("statistics-no-nav");
    return () => document.body.classList.remove("statistics-no-nav");
  }, []);
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

  return <section className="cz-page ss-page" aria-labelledby="server-statistics-title">
    <header className="cz-header"><div className="cz-header-copy"><p className="cz-eyebrow">ESPACE RESPONSABLE · OBSERVATOIRE DU SERVEUR</p><h1 id="server-statistics-title">Statistiques du serveur</h1><p className="cz-intro">Comprendre la participation, suivre les parcours et explorer les échanges. Choisissez une question, puis lisez les données à votre rythme.</p></div><div className="cz-header-actions"><Link className="cz-home" to="/">Accueil <ArrowRight size={18} aria-hidden="true" /></Link><button className="cz-button cz-button--primary" onClick={() => setVersion(value => value+1)} disabled={loading}><RefreshCw size={16} aria-hidden="true" /> Actualiser</button></div></header>
    <div className="ss-main-views"><div className="cz-tabs cz-tabs--view ss-view-tabs" role="group" aria-label="Vue des statistiques"><button className={`cz-tab ${view==="activity" ? "is-selected" : ""}`} aria-pressed={view==="activity"} onClick={()=>setView("activity")}><BarChart3 size={16} aria-hidden="true" />Activité du serveur</button><button className={`cz-tab ${view==="members" ? "is-selected" : ""}`} aria-pressed={view==="members"} onClick={()=>setView("members")}><Users size={16} aria-hidden="true" />Membres et fidélisation</button><button className={`cz-tab ${view==="interactions" ? "is-selected" : ""}`} aria-pressed={view==="interactions"} onClick={()=>setView("interactions")}><Network size={16} aria-hidden="true" />Interactions et équilibre</button></div></div>
    <section className="ss-filters" aria-label="Filtres statistiques"><div className="ss-periods" aria-label="Périodes rapides">{[["1","Aujourd’hui"],["7","7 jours"],["30","30 jours"],["year","Cette année"]].map(([value,label]) => <button type="button" className="ss-button" key={value} aria-pressed={end===today && start===(value==="year" ? `${today.slice(0,4)}-01-01` : daysBefore(today,Number(value)-1))} onClick={() => preset(value)}>{label}</button>)}</div><div className="ss-dates"><label>Du<input type="date" value={start} max={end || today} onChange={event => setStart(event.target.value)} /></label><label>Au<input type="date" value={end} min={start} max={today} onChange={event => setEnd(event.target.value)} /></label></div>
      <details className="ss-filter-drawer"><summary><SlidersHorizontal size={15} aria-hidden="true" /> Filtres et comparaison <span>{excluded.length || category || channel || member || weekday!=="" || hour!=="" ? "· Sélection personnalisée" : "· Tous les espaces"}</span></summary><p className="ss-filter-explainer">Ces choix s’appliquent à l’activité affichée. Masquer un espace ne supprime pas sa collecte ; les effectifs du serveur restent globaux.</p>
      <details className="ss-categories"><summary>Catégories affichées{excluded.length ? ` · ${excluded.length} masquée(s)` : " · Toutes"}</summary><div className="ss-category-actions"><button className="ss-button" onClick={() => setExcluded([])}>Tout afficher</button><button className="ss-button" onClick={() => setExcluded(current => [...new Set([...current, ...INTERNAL])])}>Masquer contact staff, staff et soutien</button></div><div className="ss-category-options">{(data?.categories || []).map(category => <label key={category.id}><input type="checkbox" checked={!excluded.includes(category.id)} onChange={() => toggleCategory(category.id)} />{category.name}{category.internal && <small>Espace interne</small>}</label>)}</div><p>Ces filtres modifient tous les compteurs affichés. La collecte conserve les données de toutes les catégories.</p></details>
      <div className="ss-chart-controls">
        {view==="activity" && <label>Regrouper par<select value={granularity} onChange={event=>setGranularity(event.target.value)} aria-label="Regrouper les messages">{[["hour","Heure"],["day","Jour"],["week","Semaine"],["month","Mois"],["year","Année"]].map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>}
        <label>Catégorie<select value={category} onChange={event=>pickCategory(event.target.value)} aria-label="Filtrer une catégorie"><option value="">Toutes les catégories affichées</option>{(data?.categories || []).filter(row=>!excluded.includes(row.id)).map(row=><option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
        <label>Salon<select value={channel} onChange={event=>setChannel(event.target.value)} aria-label="Filtrer un salon"><option value="">Tous les salons</option>{(data?.available_channels || []).filter(row=>(!category || row.category_id===category) && !excluded.includes(row.category_id)).map(row=><option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
        <label className="ss-compare-toggle"><input type="checkbox" checked={compare} onChange={event=>setCompare(event.target.checked)} /> Comparer à la période précédente</label>
      </div>
      </details>
      {(category || channel || member || weekday!=="" || hour!=="") && <div className="ss-active-filters" aria-label="Filtres actifs">{category && <button className="ss-button" onClick={()=>setCategory("")}>Catégorie : {data?.categories?.find(row=>row.id===category)?.name || category} ×</button>}{channel && <button className="ss-button" onClick={()=>setChannel("")}>Salon : {data?.available_channels?.find(row=>row.id===channel)?.name || channel} ×</button>}{member && <button className="ss-button" onClick={()=>setMember("")}>Membre : {data?.selected_member?.name || member} ×</button>}{weekday!=="" && <button className="ss-button" onClick={()=>setWeekday("")}>{weekdays[Number(weekday)]} ×</button>}{hour!=="" && <button className="ss-button" onClick={()=>setHour("")}>{hour} h ×</button>}<button className="ss-button" onClick={resetDetails}>Retirer les filtres d’exploration</button></div>}
    </section>
    {error && <div className="ss-notice ss-notice-error" role="alert">{error} <button className="ss-button" onClick={() => setVersion(value => value+1)}>Réessayer</button></div>}
    {loading && <p className="ss-loading" role="status">Actualisation des statistiques…</p>}
    {data && <div aria-busy={loading} className={loading || error ? "ss-results is-stale" : "ss-results"}>
      <div className="ss-status-strip" aria-label="État des données"><span><i className={`ss-dot ${collection.connected && collection.enabled ? "is-live" : ""}`} aria-hidden="true" />{status}</span><span>Heure de Paris</span><span>{excluded.length ? `${excluded.length} catégorie(s) masquée(s)` : "Toutes les catégories affichées"}</span><span>Données depuis le {dateTime(collection.started_at)}</span></div>
      {(collection.last_error || collection.last_ingest_error_at) && <p className="ss-notice ss-notice-error" role="alert">{collection.last_error || `Une interruption de collecte a été détectée le ${dateTime(collection.last_ingest_error_at)}. Les chiffres peuvent être incomplets.`}</p>}
      {view==="activity" && <>
      {data.charts && <div className={`ss-coverage ${data.charts.coverage.ratio < .98 ? "is-partial" : ""}`}><strong>Connexion du bot couverte : {coverageLabel(data.charts.coverage.ratio)}</strong><span>{number(data.charts.coverage.observed_hours)} h observées sur {number(data.charts.coverage.possible_hours)} h. Les périodes sans collecte ne sont pas assimilées à une activité nulle.</span></div>}
      <MetricCollection items={[["Messages","messages"],["Membres actifs","active_members"],["Salons actifs","active_channels"],["Pièces jointes","attachments"]].map(([label,key])=>[label,number(data.totals[key]),"Période et espaces sélectionnés.",<Delta key={key} metric={key} comparison={comparison} />])} />
      {comparison && <p className="ss-comparison-caption">Comparaison avec le {comparison.start.split("-").reverse().join("/")} au {comparison.end.split("-").reverse().join("/")}.{comparison.complete_hours_only && <> Les variations portent sur les heures complètes jusqu’au {dateTime(comparison.current_until)} ; les totaux incluent aussi l’heure en cours.</>}{!comparison.reliable && " Les pourcentages sont masqués si la connexion ou les données de collecte sont incomplètes."}</p>}
      {!data.totals.messages && <div className="ss-notice"><BarChart3 size={20} /><p>Aucun message observé pour ces filtres. Vérifiez la couverture de collecte avant de conclure à une absence d’activité.</p></div>}
      <StatisticsCharts data={data} granularity={granularity} onPeriod={explorePeriod} onCategory={pickCategory} onChannel={setChannel} onMember={setMember} onPeak={row=>{ setWeekday(String(row.weekday)); setHour(String(row.hour)); }} onHour={row=>setHour(String(row.hour))} />
      </>}
      {view==="members" && <MemberStatistics metrics={data.member_metrics} />}
      {view==="interactions" && <InteractionStatistics metrics={data.interaction_metrics} onMember={setMember} onCategory={pickCategory} />}
      <details className="ss-technical"><summary>Fiabilité des données et détails de la collecte</summary><p>Les chiffres commencent au démarrage de la collecte : une période plus ancienne n’est pas reconstituée. Une absence de connexion peut expliquer une baisse apparente d’activité.</p><dl><div><dt>Dernier signal du bot</dt><dd>{dateTime(collection.last_seen_at)}</dd></div><div><dt>Dernier calcul</dt><dd>{dateTime(collection.last_projection_at)}</dd></div><div><dt>Messages en attente</dt><dd>{number(collection.pending_messages)}</dd></div></dl>{collection.sessions.length>0 && <div className="ss-table-scroll"><table><caption>Connexions récentes du bot</caption><thead><tr><th scope="col">Connecté depuis</th><th scope="col">Dernier signal</th><th scope="col">Déconnexion</th></tr></thead><tbody>{collection.sessions.map((session,index)=><tr key={`${session.started_at}-${index}`}><td>{dateTime(session.started_at)}</td><td>{dateTime(session.last_seen_at)}</td><td>{session.ended_at ? dateTime(session.ended_at) : index===0 && collection.connected ? "En cours" : "Fin non confirmée"}</td></tr>)}</tbody></table></div>}<p>Messages humains uniquement, pièces jointes comprises. Bots et messages système exclus. Aucun texte de message n’est conservé pour les statistiques. Le registre permet les corrections pendant {collection.registry_days} jours ; une correction plus ancienne ne change pas les totaux.</p></details>
    </div>}
  </section>;
}
