import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, ArrowRight, HeartHandshake, RefreshCw, User, Users } from "lucide-react";
import { api, getErrorMessage } from "../api/client";
import StatisticsChart from "../components/statistics/StatisticsChart";
import "../Casier.css";
import "../StaffLoad.css";

const WEEK_CHOICES = [4, 8, 12];
const LEVEL_ORDER = { surcharge: 0, attention: 1, ok: 2 };
const LEVELS = {
  ok: { label: "Tout va bien", hint: "Charge confortable" },
  attention: { label: "À surveiller", hint: "Charge soutenue" },
  surcharge: { label: "Prendre des nouvelles", hint: "Charge très élevée" },
};
const PILL = { ok: "vierge", attention: "averti", surcharge: "kick" };
const number = (value) => new Intl.NumberFormat("fr-FR").format(value || 0);
const weekLabel = (iso) => (iso ? iso.slice(8, 10) + "/" + iso.slice(5, 7) : "");
const sum = (values) => (values || []).reduce((total, value) => total + (value || 0), 0);

// Couleurs reconnues par le mode sombre de StatisticsChart.
const COLORS = ["#527c66", "#a68a6b", "#839ca7"];
const CHART_BASE = {
  color: COLORS,
  textStyle: { fontFamily: "inherit", color: "#637a6b", fontSize: 11 },
  tooltip: { trigger: "axis", renderMode: "richText", confine: true, backgroundColor: "#fff", borderColor: "#dae5dc", textStyle: { color: "#365141", fontSize: 12 } },
  grid: { left: 40, right: 16, top: 36, bottom: 28 },
  legend: { top: 0, textStyle: { color: "#748478", fontSize: 11 } },
};
const AXIS = { axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: "#edf1ec" } }, axisLabel: { color: "#7b8c80" } };

function teamOption(weeks, team) {
  const labels = weeks.map((week) => "Sem. " + weekLabel(week));
  return {
    ...CHART_BASE,
    xAxis: { ...AXIS, type: "category", data: labels, splitLine: { show: false } },
    yAxis: { ...AXIS, type: "value", minInterval: 1 },
    series: [
      { name: "Suivis de tickets", type: "bar", barMaxWidth: 26, itemStyle: { color: COLORS[0], borderRadius: [4, 4, 0, 0] }, data: team.tickets_handled },
      { name: "Situations lourdes", type: "bar", barMaxWidth: 26, itemStyle: { color: COLORS[1], borderRadius: [4, 4, 0, 0] }, data: team.heavy_tickets },
      { name: "Réunions", type: "line", smooth: 0.15, symbolSize: 5, lineStyle: { width: 2 }, itemStyle: { color: COLORS[2] }, data: team.meetings },
    ],
  };
}

function messagesOption(weeks, team) {
  return {
    ...CHART_BASE,
    legend: { show: false },
    xAxis: { ...AXIS, type: "category", data: weeks.map((week) => "Sem. " + weekLabel(week)), splitLine: { show: false } },
    yAxis: { ...AXIS, type: "value", minInterval: 1 },
    series: [{ name: "Messages envoyés", type: "line", smooth: 0.15, symbolSize: 5, lineStyle: { width: 2.5 }, areaStyle: { opacity: 0.08 }, itemStyle: { color: COLORS[0] }, data: team.messages_sent }],
  };
}

function Sparkbars({ weeks, tickets, heavy, name }) {
  const max = Math.max(1, ...tickets);
  const width = 100 / Math.max(1, tickets.length);
  const summary = weeks.map((week, index) => "semaine du " + weekLabel(week) + " : " + (tickets[index] || 0) + " suivi(s), dont " + (heavy[index] || 0) + " lourd(s)").join(" ; ");
  return (
    <svg className="sl-spark" viewBox="0 0 100 36" preserveAspectRatio="none" role="img" aria-label={"Suivis de tickets par semaine pour " + name + ". " + summary}>
      <line x1="0" y1="35.5" x2="100" y2="35.5" className="sl-spark-base" />
      {tickets.map((value, index) => {
        const height = (value / max) * 32;
        const heavyHeight = ((heavy[index] || 0) / max) * 32;
        const x = index * width + width * 0.15;
        const w = width * 0.7;
        return (
          <g key={index}>
            <rect x={x} y={35 - height} width={w} height={Math.max(height, value ? 1 : 0)} rx="1" className="sl-spark-bar" />
            {heavyHeight > 0 && <rect x={x} y={35 - heavyHeight} width={w} height={heavyHeight} rx="1" className="sl-spark-heavy" />}
          </g>
        );
      })}
    </svg>
  );
}

function PersonCard({ person, weeks }) {
  const level = LEVELS[person.level] ? person.level : "ok";
  const info = LEVELS[level];
  const score = Math.max(0, Math.min(100, person.load_score || 0));
  const nightPct = Math.round((person.night_activity_ratio || 0) * 100);
  return (
    <li className={"sl-card sl-card--" + level}>
      <article aria-label={person.name + " : " + info.label}>
        <header className="sl-card-head">
          {person.avatar_url ? <img className="sl-avatar" src={person.avatar_url} alt="" width="40" height="40" loading="lazy" /> : <span className="sl-avatar sl-avatar--empty" aria-hidden="true"><User size={18} /></span>}
          <div className="sl-who">
            <h3>{person.name}</h3>
            {person.roles?.length > 0 && <p>{person.roles.join(" · ")}</p>}
          </div>
          <span className={"cz-pill cz-pill--" + PILL[level]}>{level === "surcharge" && <HeartHandshake size={14} aria-hidden="true" />}{info.label}</span>
        </header>
        <div className="sl-meter" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={score} aria-label={"Indice de charge de " + person.name + " : " + score + " sur 100, " + info.hint.toLowerCase()}>
          <span style={{ width: score + "%" }} />
        </div>
        <p className="sl-score">Indice de charge <strong>{score}</strong> / 100</p>
        {person.signals?.length > 0 ? (
          <ul className="sl-signals">{person.signals.map((signal) => <li key={signal}>{signal}</li>)}</ul>
        ) : (
          <p className="sl-quiet">Rien de particulier à signaler.</p>
        )}
        <Sparkbars weeks={weeks} tickets={person.tickets_handled || []} heavy={person.heavy_tickets || []} name={person.name} />
        <p className="sl-spark-caption">Suivis par semaine ({weekLabel(weeks[0])} – {weekLabel(weeks[weeks.length - 1])}), situations lourdes en couleur marquée.</p>
        <dl className="sl-facts">
          <div><dt>Suivis</dt><dd>{number(sum(person.tickets_handled))}</dd></div>
          <div><dt>Situations lourdes</dt><dd>{number(sum(person.heavy_tickets))}</dd></div>
          <div><dt>Réunions</dt><dd>{number(sum(person.meetings))}</dd></div>
          <div><dt>Tâches ouvertes</dt><dd>{number(person.tasks_open)}{person.tasks_overdue > 0 ? " (" + person.tasks_overdue + " en retard)" : ""}</dd></div>
          <div><dt>Messages de nuit</dt><dd>{nightPct} %</dd></div>
          <div><dt>Jours d’absence</dt><dd>{number(person.absent_days)}</dd></div>
        </dl>
      </article>
    </li>
  );
}

export default function StaffLoadPage() {
  const [weeks, setWeeks] = useState(4);
  const [view, setView] = useState("people");
  const [sort, setSort] = useState("score");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);

  useEffect(() => {
    document.body.classList.add("casier-no-nav");
    return () => document.body.classList.remove("casier-no-nav");
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api.get("/responsable/load", { params: { weeks }, signal: controller.signal })
      .then((response) => { if (!controller.signal.aborted) setData(response.data); })
      .catch((requestError) => {
        if (controller.signal.aborted || requestError?.code === "ERR_CANCELED") return;
        setError(requestError?.response?.status === 403 ? "Cette page est réservée aux responsables et aux coordinateurs." : getErrorMessage(requestError));
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [weeks, version]);

  const refresh = useCallback(() => setVersion((value) => value + 1), []);
  const people = useMemo(() => {
    const rows = [...(data?.people || [])];
    if (sort === "name") return rows.sort((a, b) => (a.name || "").localeCompare(b.name || "", "fr"));
    return rows.sort((a, b) => (b.load_score - a.load_score) || (LEVEL_ORDER[a.level] - LEVEL_ORDER[b.level]) || (a.name || "").localeCompare(b.name || "", "fr"));
  }, [data, sort]);
  const team = data?.team;
  const weekList = data?.weeks || [];
  const toCheck = team?.levels?.surcharge || 0;

  return (
    <section className="cz-page sl-page" aria-labelledby="staff-load-title">
      <header className="cz-header">
        <div className="cz-header-copy">
          <p className="cz-eyebrow">ESPACE RESPONSABLE · BIEN-ÊTRE DE L’ÉQUIPE</p>
          <h1 id="staff-load-title">Charge du staff</h1>
          <p className="cz-intro">Un regard bienveillant sur la charge de chacun, pour penser à soutenir ceux qui en portent beaucoup. Ces indices aident à prendre des nouvelles, ils ne jugent personne.</p>
        </div>
        <div className="cz-header-actions">
          <Link className="cz-home" to="/">Accueil <ArrowRight size={18} aria-hidden="true" /></Link>
        </div>
      </header>

      <section className="cz-panel sl-panel-main" aria-labelledby="sl-panel-title">
        <header className="cz-panel-header">
          <span className="cz-panel-icon" aria-hidden="true"><HeartHandshake size={23} /></span>
          <div className="cz-panel-heading">
            <h2 id="sl-panel-title">{view === "people" ? "Charge par personne" : "Charge de l’équipe"}</h2>
            <p>Sur les {weeks} dernières semaines. Des repères pour prendre des nouvelles, jamais un jugement.</p>
          </div>
          {data && !error && (
            <span className="cz-count-live">
              <span className="cz-count">{number(team?.people_count ?? people.length)} {(team?.people_count ?? people.length) > 1 ? "personnes" : "personne"}</span>
            </span>
          )}
        </header>

        <div className="cz-panel-toolbar sl-toolbar">
          <div className="cz-chips" role="group" aria-label="Période analysée">
            {WEEK_CHOICES.map((choice) => (
              <button key={choice} type="button" className="cz-chip" aria-pressed={weeks === choice} onClick={() => setWeeks(choice)}>{choice} semaines</button>
            ))}
          </div>
          <div className="cz-tabs cz-tabs--view sl-views" role="group" aria-label="Vue">
            <button type="button" className={"cz-tab" + (view === "people" ? " is-selected" : "")} aria-pressed={view === "people"} onClick={() => setView("people")}><User size={16} aria-hidden="true" /> Personnes</button>
            <button type="button" className={"cz-tab" + (view === "team" ? " is-selected" : "")} aria-pressed={view === "team"} onClick={() => setView("team")}><Users size={16} aria-hidden="true" /> Équipe</button>
          </div>
          {view === "people" && (
            <label className="sl-sort">Trier par
              <select value={sort} onChange={(event) => setSort(event.target.value)}>
                <option value="score">Indice de charge (du plus élevé)</option>
                <option value="name">Nom</option>
              </select>
            </label>
          )}
          <button type="button" className="cz-button sl-refresh" onClick={refresh} disabled={loading}><RefreshCw size={16} className={loading ? "cz-spin" : undefined} aria-hidden="true" /> Actualiser</button>
        </div>

        <div className="cz-panel-body">
          {error && (
            <div className="cz-empty cz-empty--error cz-empty--compact" role="alert">
              <AlertCircle size={26} aria-hidden="true" />
              <p>{error}</p>
            </div>
          )}
          {loading && !data && !error && (
            <div role="status">
              <span className="cz-sr-only">Chargement…</span>
              <ul className="sl-grid" aria-hidden="true">
                {[0, 1, 2].map((key) => (
                  <li key={key} className="sl-card cz-skeleton-card">
                    <div className="cz-skeleton-row cz-skeleton-row--flush"><span className="cz-skeleton cz-skeleton--circle" /><div className="cz-skeleton-stack"><span className="cz-skeleton cz-skeleton--title" /><span className="cz-skeleton cz-skeleton--short" /></div></div>
                    <span className="cz-skeleton cz-skeleton--block" />
                  </li>
                ))}
              </ul>
            </div>
          )}
          {loading && data && !error && <p className="cz-sr-only" role="status">Chargement…</p>}

          {data && !error && (
            <div aria-busy={loading} className={loading ? "sl-results is-stale" : "sl-results"}>
              {toCheck > 0 && (
                <p className="sl-care" role="status">
                  <HeartHandshake size={18} aria-hidden="true" />
                  <span>{toCheck === 1 ? "1 personne porte une charge très élevée" : toCheck + " personnes portent une charge très élevée"} en ce moment. Un petit message pour prendre des nouvelles peut faire du bien.</span>
                </p>
              )}

              {view === "people" && (
                people.length === 0 ? (
                  <div className="cz-empty">
                    <Users size={28} aria-hidden="true" />
                    <p className="sl-empty">Aucune personne à afficher pour cette période.</p>
                  </div>
                ) : (
                  <ul className="sl-grid" aria-label="Charge par personne">
                    {people.map((person) => <PersonCard key={person.user_id} person={person} weeks={weekList} />)}
                  </ul>
                )
              )}

              {view === "team" && team && (
                <>
                  <ul className="sl-kpis" aria-label="Chiffres de l’équipe">
                    <li><span>Personnes suivies</span><strong>{number(team.people_count)}</strong></li>
                    <li><span>Indice moyen</span><strong>{number(team.average_load_score)} / 100</strong></li>
                    <li><span>Tout va bien</span><strong>{number(team.levels?.ok)}</strong></li>
                    <li><span>À surveiller</span><strong>{number(team.levels?.attention)}</strong></li>
                    <li><span>À soutenir</span><strong>{number(team.levels?.surcharge)}</strong></li>
                    <li><span>Tâches ouvertes</span><strong>{number(team.tasks_open)}</strong><small>{number(team.tasks_overdue)} en retard</small></li>
                    <li><span>Jours d’absence</span><strong>{number(team.absent_days)}</strong></li>
                  </ul>
                  <div className="sl-charts">
                    <section className="sl-panel" aria-labelledby="sl-chart-1">
                      <h2 id="sl-chart-1">Suivis, situations lourdes et réunions</h2>
                      <StatisticsChart option={teamOption(weekList, team)} label="Suivis de tickets, situations lourdes et réunions de l’équipe par semaine" height={280} />
                    </section>
                    <section className="sl-panel" aria-labelledby="sl-chart-2">
                      <h2 id="sl-chart-2">Messages envoyés</h2>
                      <StatisticsChart option={messagesOption(weekList, team)} label="Messages envoyés par l’équipe, par semaine" height={280} />
                    </section>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </section>
    </section>
  );
}
