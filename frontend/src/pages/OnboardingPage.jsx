import "../Team.css";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import TeamHeader from "../components/team/TeamHeader";
import {
  errorMessage, fetchChecklist, fetchOverview, fetchTemplates, formatDate, nudgeMember,
  resetTemplate, saveTemplate, setChecklistItem, teamKeys,
} from "../components/team/teamApi";

function Progress({ percent, label }) {
  return (
    <div className="tm-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-label={label}>
      <div className="tm-progress-bar" style={{ width: `${percent}%` }} />
    </div>
  );
}

function MyChecklist() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: teamKeys.onboarding, queryFn: fetchChecklist });
  const toggle = useMutation({
    mutationFn: ({ id, done }) => setChecklistItem(id, done),
    onSuccess: (data) => qc.setQueryData(teamKeys.onboarding, (old) => ({ ...(old || {}), ...data })),
    onError: (err) => toast.error(errorMessage(err)),
  });
  const data = query.data;
  return (
    <section className="tm-panel" aria-labelledby="ob-mine">
      <h2 id="ob-mine">Mon parcours d'accueil</h2>
      {query.isLoading && <p className="tm-state" role="status">Chargement…</p>}
      {query.isError && <p className="tm-state tm-state--error" role="alert">{errorMessage(query.error)}</p>}
      {data && (
        <>
          <p className="tm-meta">{data.done}/{data.total} étapes · {data.percent} %</p>
          <Progress percent={data.percent} label="Avancement de mon parcours" />
          <ul className="tm-checks">
            {data.items.map((it) => (
              <li key={it.id}>
                <label className={`tm-check${it.done ? " is-done" : ""}`}>
                  <input type="checkbox" checked={it.done} disabled={toggle.isPending}
                    onChange={(e) => toggle.mutate({ id: it.id, done: e.target.checked })} />
                  <span>{it.label}</span>
                  <span className="tm-chip tm-chip--soft">{it.role_label}</span>
                </label>
              </li>
            ))}
          </ul>
          {data.total > 0 && data.percent === 100 && <p className="tm-ok" role="status">Parcours terminé, bienvenue dans l'équipe !</p>}
        </>
      )}
    </section>
  );
}

function TemplateEditor({ tpl }) {
  const qc = useQueryClient();
  const [items, setItems] = useState(tpl.items);
  useEffect(() => setItems(tpl.items), [tpl]);
  const refresh = () => { qc.invalidateQueries({ queryKey: teamKeys.templates }); qc.invalidateQueries({ queryKey: ["team", "onboarding"] }); };
  const save = useMutation({
    mutationFn: () => saveTemplate(tpl.role, items.filter((i) => i.label.trim())),
    onSuccess: () => { toast.success(`Modèle « ${tpl.label} » enregistré.`); refresh(); },
    onError: (err) => toast.error(errorMessage(err)),
  });
  const reset = useMutation({
    mutationFn: () => resetTemplate(tpl.role),
    onSuccess: () => { toast.success("Modèle par défaut rétabli."); refresh(); },
    onError: (err) => toast.error(errorMessage(err)),
  });
  const move = (i, d) => {
    const next = [...items]; const j = i + d;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]]; setItems(next);
  };
  return (
    <details className="tm-details">
      <summary>{tpl.label} · {tpl.items.length} étapes{tpl.customized ? " · personnalisé" : ""}</summary>
      <ul className="tm-edit-list">
        {items.map((it, i) => (
          <li key={it.id || i} className="tm-slot tm-slot--edit">
            <input className="tm-input" aria-label={`Étape ${i + 1}`} maxLength={140} value={it.label}
              onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
            <button type="button" className="tm-btn" aria-label="Monter" onClick={() => move(i, -1)}>↑</button>
            <button type="button" className="tm-btn" aria-label="Descendre" onClick={() => move(i, 1)}>↓</button>
            <button type="button" className="tm-btn tm-btn--danger" onClick={() => setItems(items.filter((_, j) => j !== i))}>Retirer</button>
          </li>
        ))}
      </ul>
      <div className="tm-actions">
        {items.length < 30 && <button type="button" className="tm-btn" onClick={() => setItems([...items, { label: "" }])}>Ajouter une étape</button>}
        <button type="button" className="tm-btn tm-btn--primary" disabled={save.isPending} onClick={() => save.mutate()}>Enregistrer</button>
        {tpl.customized && <button type="button" className="tm-btn" disabled={reset.isPending} onClick={() => reset.mutate()}>Rétablir le défaut</button>}
      </div>
    </details>
  );
}

function Tracking() {
  const overview = useQuery({ queryKey: teamKeys.overview, queryFn: fetchOverview });
  const templates = useQuery({ queryKey: teamKeys.templates, queryFn: fetchTemplates });
  const nudge = useMutation({
    mutationFn: nudgeMember,
    onSuccess: (r) => (r.sent ? toast.success("Rappel envoyé.") : toast.info("Un rappel a déjà été envoyé aujourd'hui.")),
    onError: (err) => toast.error(errorMessage(err)),
  });
  return (
    <>
      <section className="tm-panel" aria-labelledby="ob-follow">
        <h2 id="ob-follow">Suivi de l'équipe{overview.data ? ` · ${overview.data.incomplete} en cours` : ""}</h2>
        {overview.isLoading && <p className="tm-state" role="status">Chargement…</p>}
        {overview.isError && <p className="tm-state tm-state--error" role="alert">{errorMessage(overview.error)}</p>}
        <ul className="tm-list">
          {(overview.data?.items ?? []).map((r) => (
            <li className="tm-card" key={r.id}>
              <div className="tm-card-head">
                <strong>{r.name}</strong>
                <span className="tm-meta">{r.done}/{r.total} · {r.percent} %{r.last_activity ? ` · dernière activité ${formatDate(r.last_activity)}` : " · pas commencé"}</span>
              </div>
              <Progress percent={r.percent} label={`Avancement de ${r.name}`} />
              {r.percent < 100 && (
                <>
                  <p className="tm-meta">Reste : {r.missing.join(" · ")}</p>
                  <div className="tm-actions">
                    <button type="button" className="tm-btn" disabled={nudge.isPending} onClick={() => nudge.mutate(r.id)}>Envoyer un rappel</button>
                  </div>
                </>
              )}
            </li>
          ))}
        </ul>
      </section>
      <section className="tm-panel" aria-labelledby="ob-tpl">
        <h2 id="ob-tpl">Modèles de checklist par rôle</h2>
        {templates.isError && <p className="tm-state tm-state--error" role="alert">{errorMessage(templates.error)}</p>}
        {(templates.data?.items ?? []).map((t) => <TemplateEditor key={t.role} tpl={t} />)}
      </section>
    </>
  );
}

export default function OnboardingPage({ isResponsable = false }) {
  return (
    <section className="tm-page" data-testid="onboarding-page">
      <TeamHeader eyebrow="ESPACE STAFF · ÉQUIPE" title="Parcours d'accueil"
        intro="Les premières étapes pour bien démarrer dans l'équipe." />
      <div className="tm-stack">
        <MyChecklist />
        {isResponsable && <Tracking />}
      </div>
    </section>
  );
}
