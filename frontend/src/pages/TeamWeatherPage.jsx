import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import WellbeingShell from "../components/wellbeing/WellbeingShell";
import { errorMessage, sendCheckin, weatherStatus, weatherSummary } from "../components/wellbeing/wellbeingApi";

const MOODS = [["😞", "Très bas"], ["😕", "Bas"], ["😐", "Moyen"], ["🙂", "Bien"], ["😄", "Très bien"]];
const ENERGY = [["🪫", "À plat"], ["😴", "Faible"], ["🔋", "Correct"], ["⚡", "Bon"], ["🚀", "Plein"]];
const formatWeek = (iso) => `Semaine du ${new Date(`${iso}T12:00:00`).toLocaleDateString("fr-FR", { day: "numeric", month: "long" })}`;

function Scale({ name, legend, options, value, onChange }) {
  return (
    <fieldset className="wb-scale">
      <legend>{legend}</legend>
      <div className="wb-scale-options">
        {options.map(([icon, label], index) => (
          <label key={label} className={`wb-scale-option${value === index + 1 ? " is-on" : ""}`}>
            <input type="radio" name={name} value={index + 1} checked={value === index + 1} onChange={() => onChange(index + 1)} />
            <span className="wb-scale-icon" aria-hidden="true">{icon}</span>
            <span>{label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function Bar({ label, value, kind }) {
  return (
    <div className="wb-metric">
      <span>{label}</span>
      <div className={`wb-bar wb-bar--${kind}${value <= 2.5 ? " wb-bar--low" : ""}`} role="img" aria-label={`${label} : ${value} sur 5`}>
        <span style={{ width: `${(value / 5) * 100}%` }} />
      </div>
      <strong>{value.toFixed(1)}</strong>
    </div>
  );
}

function CheckinForm({ onDone }) {
  const [mood, setMood] = useState(0);
  const [energy, setEnergy] = useState(0);
  const [word, setWord] = useState("");
  const send = useMutation({
    mutationFn: () => sendCheckin({ mood, energy, word }),
    onSuccess: () => { toast.success("Merci, ta réponse est enregistrée anonymement."); onDone(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <form className="wb-stack" onSubmit={(e) => { e.preventDefault(); send.mutate(); }}>
      <Scale name="mood" legend="Ton humeur cette semaine" options={MOODS} value={mood} onChange={setMood} />
      <Scale name="energy" legend="Ton énergie" options={ENERGY} value={energy} onChange={setEnergy} />
      <label className="wb-stack">
        <span className="wb-label">Un mot libre (facultatif)</span>
        <textarea className="wb-textarea" maxLength={280} rows={3} value={word} onChange={(e) => setWord(e.target.value)} />
        <span className="wb-count">{word.length}/280</span>
      </label>
      <p className="wb-muted">Réponse anonyme : seuls des chiffres regroupés d’au moins 3 personnes sont visibles des responsables. Évite d’écrire des détails qui te rendraient reconnaissable.</p>
      <button type="submit" className="wb-btn wb-btn--primary" disabled={!mood || !energy || send.isPending}>Envoyer anonymement</button>
    </form>
  );
}

function Summary() {
  const query = useQuery({ queryKey: ["team-weather", "summary"], queryFn: () => weatherSummary(8) });
  if (query.isLoading) return <p className="wb-state" role="status">Chargement…</p>;
  if (query.isError) return <p className="wb-state wb-state--error" role="alert">{errorMessage(query.error)}</p>;
  const { weeks, min_responses: min, current_week: current } = query.data;
  return (
    <div className="wb-stack">
      <p className="wb-muted">Cette semaine : {current.count} réponse{current.count > 1 ? "s" : ""} (détails visibles une fois la semaine terminée, à partir de {min} réponses).</p>
      {weeks.length === 0 && <p className="wb-state">Aucune semaine terminée pour le moment.</p>}
      <ul className="wb-weeks">
        {weeks.map((w) => (
          <li key={w.week} className="wb-week">
            <div className="wb-week-head"><span>{formatWeek(w.week)}</span><span>{w.count} réponse{w.count > 1 ? "s" : ""}</span></div>
            {w.hidden
              ? <p className="wb-muted">Pas assez de réponses ({w.count}/{min}) pour garantir l’anonymat.</p>
              : (<>
                  <Bar label="Humeur" value={w.mood_avg} kind="mood" />
                  <Bar label="Énergie" value={w.energy_avg} kind="energy" />
                  {w.words.length > 0 && (
                    <ul className="wb-words" aria-label="Mots libres, sans ordre ni auteur">
                      {w.words.map((word, i) => <li key={`${i}-${word}`}>{word}</li>)}
                    </ul>
                  )}
                </>)}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function TeamWeatherPage() {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["team-weather", "status"], queryFn: weatherStatus });
  const data = status.data;
  return (
    <WellbeingShell eyebrow="ESPACE ÉQUIPE · BIEN-ÊTRE" title="Météo de l’équipe" testId="team-weather-page"
      intro="Un check-in hebdomadaire, anonyme et rapide, pour repérer les coups de fatigue collectifs.">
      {status.isLoading && <p className="wb-state" role="status">Chargement…</p>}
      {status.isError && <p className="wb-state wb-state--error" role="alert">{errorMessage(status.error)}</p>}
      {data && (
        <div className={data.can_view_summary ? "wb-grid" : "wb-stack"} style={data.can_view_summary ? undefined : { maxWidth: 520 }}>
          <div className="wb-panel">
            <h2>{data.submitted ? "Merci pour ta réponse" : "Ton check-in de la semaine"}</h2>
            {data.submitted
              ? <p className="wb-muted" data-testid="weather-done">Tu as répondu cette semaine. À lundi prochain !</p>
              : <CheckinForm onDone={() => qc.invalidateQueries({ queryKey: ["team-weather"] })} />}
          </div>
          {data.can_view_summary && <div className="wb-panel"><h2>Tendance de l’équipe</h2><Summary /></div>}
        </div>
      )}
    </WellbeingShell>
  );
}
