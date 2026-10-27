import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, Download, Printer, RefreshCw } from "lucide-react";
import { api, getErrorMessage } from "../api/client";
import StatisticsChart from "../components/statistics/StatisticsChart";
import "@/Casier.css";
import "@/MonthlyReport.css";

const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;
const number = (value) => new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 }).format(value || 0);
const dayMonth = (iso) => (iso ? iso.slice(8, 10) + "/" + iso.slice(5, 7) : "");
const SANCTION_LABELS = {
  avertissement: "Avertissement", mute: "Mute", kick: "Expulsion", bannissement: "Bannissement", rappel_a_lordre: "Rappel à l’ordre",
};
const CRISIS_LABELS = { vigilance: "Vigilance", eleve: "Élevé", urgence: "Urgence" };

function monthLabel(month) {
  if (!MONTH_RE.test(month || "")) return month || "";
  const text = new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5)) - 1, 1)).toLocaleDateString("fr-FR", { month: "long", year: "numeric", timeZone: "UTC" });
  return text.charAt(0).toUpperCase() + text.slice(1);
}

// Couleurs reconnues par le mode sombre de StatisticsChart.
const COLORS = ["#527c66", "#a68a6b", "#839ca7"];
const BASE = {
  color: COLORS,
  textStyle: { fontFamily: "inherit", color: "#637a6b", fontSize: 11 },
  tooltip: { trigger: "axis", renderMode: "richText", confine: true, backgroundColor: "#fff", borderColor: "#dae5dc", textStyle: { color: "#365141", fontSize: 12 } },
  grid: { left: 44, right: 20, top: 36, bottom: 28 },
  legend: { top: 0, textStyle: { color: "#748478", fontSize: 11 } },
};
const AXIS = { axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: "#edf1ec" } }, axisLabel: { color: "#7b8c80" } };

function weeksOption(weeks) {
  return {
    ...BASE,
    xAxis: { ...AXIS, type: "category", splitLine: { show: false }, data: weeks.map((w) => "Sem. " + dayMonth(w.week_start)) },
    yAxis: { ...AXIS, type: "value", minInterval: 1 },
    series: [
      { name: "Ouverts", type: "bar", barMaxWidth: 28, itemStyle: { color: COLORS[0], borderRadius: [4, 4, 0, 0] }, data: weeks.map((w) => w.opened) },
      { name: "Clôturés", type: "bar", barMaxWidth: 28, itemStyle: { color: COLORS[2], borderRadius: [4, 4, 0, 0] }, data: weeks.map((w) => w.closed) },
    ],
  };
}

function columnsOption(entries, color) {
  return {
    ...BASE,
    legend: { show: false },
    tooltip: { ...BASE.tooltip, trigger: "item" },
    xAxis: { ...AXIS, type: "category", splitLine: { show: false }, data: entries.map(([label]) => label), axisLabel: { color: "#7b8c80", interval: 0, fontSize: 10 } },
    yAxis: { ...AXIS, type: "value", minInterval: 1 },
    series: [{ type: "bar", barMaxWidth: 40, itemStyle: { color, borderRadius: [4, 4, 0, 0] }, label: { show: true, position: "top", color: "#617a67", fontSize: 11 }, data: entries.map(([, value]) => value) }],
  };
}

function Trend({ value, lowerIsBetter }) {
  if (value === null || value === undefined) return <small className="mr-trend">Pas de comparaison possible</small>;
  if (value === 0) return <small className="mr-trend">Stable vs mois précédent</small>;
  const up = value > 0;
  const tone = lowerIsBetter === undefined ? "" : (up === lowerIsBetter ? " is-warn" : " is-good");
  return <small className={"mr-trend" + tone}>{up ? "▲" : "▼"} {up ? "+" : ""}{number(value)} % vs mois précédent</small>;
}

function Kpi({ label, value, unit, trend, lowerIsBetter }) {
  return (
    <li className="mr-kpi">
      <span>{label}</span>
      <strong>{value === null || value === undefined ? "—" : number(value)}{value !== null && value !== undefined && unit ? " " + unit : ""}</strong>
      <Trend value={trend} lowerIsBetter={lowerIsBetter} />
    </li>
  );
}

export default function MonthlyReportPage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("month");
  const month = MONTH_RE.test(requested || "") ? requested : "";
  const [months, setMonths] = useState([]);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [exportError, setExportError] = useState("");
  const [version, setVersion] = useState(0);
  const [refresh, setRefresh] = useState(false);

  useEffect(() => {
    document.body.classList.add("casier-no-nav");
    return () => document.body.classList.remove("casier-no-nav");
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    api.get("/responsable/reports/months", { signal: controller.signal })
      .then((response) => { if (!controller.signal.aborted) setMonths(Array.isArray(response.data?.months) ? response.data.months : []); })
      .catch(() => { /* la liste reste vide : le rapport par défaut s'affiche quand même */ });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    const query = { signal: controller.signal, params: { ...(month ? { month } : {}), ...(refresh ? { refresh: 1 } : {}) } };
    api.get("/responsable/reports/monthly", query)
      .then((response) => { if (!controller.signal.aborted) setReport(response.data); })
      .catch((requestError) => {
        if (controller.signal.aborted || requestError?.code === "ERR_CANCELED") return;
        setError(requestError?.response?.status === 403 ? "Cette page est réservée aux responsables et aux coordinateurs." : getErrorMessage(requestError));
      })
      .finally(() => { if (!controller.signal.aborted) { setLoading(false); setRefresh(false); } });
    return () => controller.abort();
  }, [month, version]); // eslint-disable-line react-hooks/exhaustive-deps

  const shownMonth = report?.month || month;
  const options = useMemo(() => {
    const list = [...months];
    if (shownMonth && !list.includes(shownMonth)) list.unshift(shownMonth);
    return list;
  }, [months, shownMonth]);

  const exportCsv = useCallback(async () => {
    setExportError("");
    try {
      const response = await api.get("/responsable/reports/monthly.csv", { params: shownMonth ? { month: shownMonth } : {}, responseType: "blob" });
      const url = URL.createObjectURL(response.data);
      const link = document.createElement("a");
      link.href = url;
      link.download = "rapport-" + (shownMonth || "mensuel") + ".csv";
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (requestError) {
      setExportError(requestError?.response?.status ? "Export impossible pour le moment. Réessayez." : getErrorMessage(requestError));
    }
  }, [shownMonth]);

  const t = report?.tickets;
  const m = report?.moderation;
  const s = report?.staff;
  const p = report?.projects;
  const trends = report?.trends || {};
  const sanctionsTotal = m ? Object.values(m.sanctions_by_type || {}).reduce((a, b) => a + b, 0) : 0;
  const sanctionEntries = m ? Object.entries(m.sanctions_by_type || {}).map(([k, v]) => [SANCTION_LABELS[k] || k, v]) : [];
  const crisisEntries = t ? Object.entries(t.crisis || {}).map(([k, v]) => [CRISIS_LABELS[k] || k, v]) : [];

  return (
    <section className="cz-page mr-page" aria-labelledby="monthly-report-title">
      <header className="cz-header">
        <div className="cz-header-copy">
          <p className="cz-eyebrow">ESPACE RESPONSABLE · RAPPORT MENSUEL</p>
          <h1 id="monthly-report-title">Rapport mensuel{shownMonth ? " · " + monthLabel(shownMonth) : ""}</h1>
          <p className="cz-intro">Le mois en un coup d’œil : tickets, situations de crise, modération et vie de l’équipe. Les chiffres sont agrégés, sans donnée nominative de membre.</p>
          {report?.generated_at && <p className="mr-print-meta">Généré le {new Date(report.generated_at).toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short", timeZone: "Europe/Paris" })}</p>}
        </div>
        <div className="cz-header-actions">
          <Link className="cz-home" to="/">Accueil <ArrowRight size={18} aria-hidden="true" /></Link>
        </div>
      </header>

      <div className="mr-toolbar mr-noprint">
        <label className="mr-month">Mois
          <select value={shownMonth} onChange={(event) => setParams(event.target.value ? { month: event.target.value } : {})} disabled={options.length === 0}>
            {options.length === 0 && <option value="">Mois précédent</option>}
            {options.map((value) => <option key={value} value={value}>{monthLabel(value)}</option>)}
          </select>
        </label>
        <div className="mr-actions">
          <button type="button" className="cz-button" onClick={() => { setRefresh(true); setVersion((v) => v + 1); }} disabled={loading}><RefreshCw size={16} aria-hidden="true" /> Recalculer</button>
          <button type="button" className="cz-button" onClick={exportCsv} disabled={!report}><Download size={16} aria-hidden="true" /> Exporter CSV</button>
          <button type="button" className="cz-button cz-button--primary" onClick={() => window.print()} disabled={!report}><Printer size={16} aria-hidden="true" /> Imprimer / PDF</button>
        </div>
      </div>

      {exportError && <p className="mr-notice mr-notice--error mr-noprint" role="alert">{exportError}</p>}
      {error && <p className="mr-notice mr-notice--error" role="alert">{error}</p>}
      {loading && <p className="mr-notice mr-noprint" role="status">Chargement du rapport…</p>}

      {report && !error && (
        <div aria-busy={loading} className={loading ? "mr-body is-stale" : "mr-body"}>
          <section aria-labelledby="mr-h-kpi" className="mr-block">
            <h2 id="mr-h-kpi">Chiffres clés</h2>
            <ul className="mr-kpis">
              <Kpi label="Tickets ouverts" value={t.opened} trend={trends.tickets_opened} />
              <Kpi label="Tickets clôturés" value={t.closed} trend={trends.tickets_closed} />
              <Kpi label="Premier retour (médiane)" value={t.median_first_response_min} unit="min" trend={trends.median_first_response_min} lowerIsBetter />
              <Kpi label="Retours hors délai" value={t.sla_breaches} trend={trends.sla_breaches} lowerIsBetter />
              <Kpi label="Sanctions" value={sanctionsTotal} trend={trends.sanctions} />
              <Kpi label="Signalements IA" value={m.ai_flags} trend={trends.ai_flags} />
              <Kpi label="Tâches terminées" value={s.tasks_done} trend={trends.tasks_done} />
              <Kpi label="Réunions" value={s.meetings} trend={trends.meetings} />
            </ul>
          </section>

          {report.highlights?.length > 0 && (
            <section aria-labelledby="mr-h-high" className="mr-block">
              <h2 id="mr-h-high">Faits marquants</h2>
              <ul className="mr-highlights">{report.highlights.map((line, index) => <li key={index}>{line}</li>)}</ul>
            </section>
          )}

          <div className="mr-charts">
            <section className="mr-panel mr-wide" aria-labelledby="mr-h-weeks">
              <h2 id="mr-h-weeks">Tickets par semaine</h2>
              <StatisticsChart option={weeksOption(t.by_week || [])} label="Tickets ouverts et clôturés par semaine" height={270} />
            </section>
            <section className="mr-panel" aria-labelledby="mr-h-crisis">
              <h2 id="mr-h-crisis">Situations de crise</h2>
              <p className="mr-sub">Niveau relevé sur les tickets ouverts dans le mois.</p>
              <StatisticsChart option={columnsOption(crisisEntries, COLORS[1])} label={"Situations de crise : " + crisisEntries.map(([k, v]) => k + " " + v).join(", ")} height={240} />
            </section>
            <section className="mr-panel" aria-labelledby="mr-h-sanctions">
              <h2 id="mr-h-sanctions">Sanctions par type</h2>
              <p className="mr-sub">{sanctionsTotal} sanction(s) ; {m.false_positives} faux positif(s) parmi les {m.ai_flags} signalement(s) IA.</p>
              <StatisticsChart option={columnsOption(sanctionEntries, COLORS[0])} label={"Sanctions par type : " + sanctionEntries.map(([k, v]) => k + " " + v).join(", ")} height={240} />
            </section>
          </div>

          <div className="mr-charts">
            <section className="mr-panel" aria-labelledby="mr-h-staff">
              <h2 id="mr-h-staff">Vie de l’équipe</h2>
              <dl className="mr-dl">
                <div><dt>Helpers actifs</dt><dd>{number(s.active_helpers)}</dd></div>
                <div><dt>Réunions tenues</dt><dd>{number(s.meetings)}</dd></div>
                <div><dt>Tâches terminées</dt><dd>{number(s.tasks_done)}</dd></div>
                <div><dt>Tâches en retard</dt><dd>{number(s.tasks_overdue)}</dd></div>
                <div><dt>Jours d’absence</dt><dd>{number(s.absences_days)}</dd></div>
              </dl>
            </section>
            <section className="mr-panel" aria-labelledby="mr-h-proj">
              <h2 id="mr-h-proj">Projets</h2>
              <dl className="mr-dl">
                <div><dt>Créés</dt><dd>{number(p.created)}</dd></div>
                <div><dt>En cours</dt><dd>{number(p.active)}</dd></div>
                <div><dt>Terminés</dt><dd>{number(p.completed)}</dd></div>
                <div><dt>Tâches créées</dt><dd>{number(p.tasks_created)}</dd></div>
              </dl>
            </section>
            <section className="mr-panel" aria-labelledby="mr-h-sla">
              <h2 id="mr-h-sla">Délais de premier retour</h2>
              <dl className="mr-dl">
                <div><dt>Médiane</dt><dd>{t.median_first_response_min == null ? "—" : number(t.median_first_response_min) + " min"}</dd></div>
                <div><dt>90e percentile</dt><dd>{t.p90_first_response_min == null ? "—" : number(t.p90_first_response_min) + " min"}</dd></div>
                <div><dt>Hors délai (60 min)</dt><dd>{number(t.sla_breaches)}</dd></div>
              </dl>
            </section>
          </div>
        </div>
      )}
    </section>
  );
}
