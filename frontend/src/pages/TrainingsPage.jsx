import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";
import WellbeingShell from "../components/wellbeing/WellbeingShell";
import {
  createTraining, deleteTraining, errorMessage, getTraining, listTrainings, submitQuiz, trainingProgress, updateTraining,
} from "../components/wellbeing/wellbeingApi";

const blankQuestion = () => ({ text: "", options: ["", ""], correct: 0, explanation: "" });
const blank = () => ({ title: "", summary: "", duration_min: 5, pass_percent: 70, published: false, sections: [{ heading: "", body: "" }], questions: [blankQuestion()] });

function Editor({ initial, onDone, onCancel, id }) {
  const [m, setM] = useState(initial);
  const set = (patch) => setM((cur) => ({ ...cur, ...patch }));
  const setSection = (i, patch) => set({ sections: m.sections.map((s, k) => (k === i ? { ...s, ...patch } : s)) });
  const setQuestion = (i, patch) => set({ questions: m.questions.map((q, k) => (k === i ? { ...q, ...patch } : q)) });
  const save = useMutation({
    mutationFn: () => {
      const payload = { ...m, duration_min: Number(m.duration_min), pass_percent: Number(m.pass_percent) };
      return id ? updateTraining(id, payload) : createTraining(payload);
    },
    onSuccess: () => { toast.success("Formation enregistrée."); onDone(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <form className="wb-editor" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <label className="wb-stack"><span className="wb-label">Titre</span><input className="wb-input" maxLength={120} required value={m.title} onChange={(e) => set({ title: e.target.value })} /></label>
      <label className="wb-stack"><span className="wb-label">Résumé</span><textarea className="wb-textarea" maxLength={400} rows={2} value={m.summary} onChange={(e) => set({ summary: e.target.value })} /></label>
      <div className="wb-row">
        <label className="wb-stack"><span className="wb-label">Durée (min)</span><input className="wb-input" type="number" min={1} max={60} value={m.duration_min} onChange={(e) => set({ duration_min: e.target.value })} /></label>
        <label className="wb-stack"><span className="wb-label">Réussite (%)</span><input className="wb-input" type="number" min={0} max={100} value={m.pass_percent} onChange={(e) => set({ pass_percent: e.target.value })} /></label>
        <label className="wb-check"><input type="checkbox" checked={m.published} onChange={(e) => set({ published: e.target.checked })} /> Publiée</label>
      </div>
      <h3>Contenu</h3>
      {m.sections.map((s, i) => (
        <div key={i} className="wb-subcard">
          <input className="wb-input" aria-label={`Titre de la section ${i + 1}`} placeholder="Titre de la section" maxLength={120} required value={s.heading} onChange={(e) => setSection(i, { heading: e.target.value })} />
          <textarea className="wb-textarea" aria-label={`Texte de la section ${i + 1}`} rows={4} maxLength={4000} required value={s.body} onChange={(e) => setSection(i, { body: e.target.value })} />
          {m.sections.length > 1 && <button type="button" className="wb-btn wb-btn--danger" onClick={() => set({ sections: m.sections.filter((_, k) => k !== i) })}><Trash2 size={14} aria-hidden="true" /> Retirer</button>}
        </div>
      ))}
      {m.sections.length < 12 && <button type="button" className="wb-btn" onClick={() => set({ sections: [...m.sections, { heading: "", body: "" }] })}><Plus size={14} aria-hidden="true" /> Section</button>}
      <h3>Quiz</h3>
      {m.questions.map((q, i) => (
        <div key={i} className="wb-subcard">
          <input className="wb-input" aria-label={`Question ${i + 1}`} placeholder="Question" maxLength={300} required value={q.text} onChange={(e) => setQuestion(i, { text: e.target.value })} />
          {q.options.map((opt, k) => (
            <div key={k} className="wb-row">
              <input type="radio" name={`correct-${i}`} aria-label={`Bonne réponse : option ${k + 1}`} checked={q.correct === k} onChange={() => setQuestion(i, { correct: k })} />
              <input className="wb-input" style={{ flex: 1 }} aria-label={`Question ${i + 1}, option ${k + 1}`} maxLength={200} required value={opt}
                onChange={(e) => setQuestion(i, { options: q.options.map((o, j) => (j === k ? e.target.value : o)) })} />
              {q.options.length > 2 && (
                <button type="button" className="wb-btn" aria-label="Retirer l’option"
                  onClick={() => setQuestion(i, { options: q.options.filter((_, j) => j !== k), correct: q.correct === k ? 0 : q.correct > k ? q.correct - 1 : q.correct })}><Trash2 size={14} aria-hidden="true" /></button>
              )}
            </div>
          ))}
          {q.options.length < 6 && <button type="button" className="wb-btn" onClick={() => setQuestion(i, { options: [...q.options, ""] })}>Ajouter une option</button>}
          <input className="wb-input" aria-label={`Explication de la question ${i + 1}`} placeholder="Explication affichée après la réponse (facultatif)" maxLength={500} value={q.explanation} onChange={(e) => setQuestion(i, { explanation: e.target.value })} />
          <button type="button" className="wb-btn wb-btn--danger" onClick={() => set({ questions: m.questions.filter((_, k) => k !== i) })}><Trash2 size={14} aria-hidden="true" /> Retirer la question</button>
        </div>
      ))}
      {m.questions.length < 20 && <button type="button" className="wb-btn" onClick={() => set({ questions: [...m.questions, blankQuestion()] })}><Plus size={14} aria-hidden="true" /> Question</button>}
      <div className="wb-row">
        <button type="submit" className="wb-btn wb-btn--primary" disabled={save.isPending}>Enregistrer</button>
        <button type="button" className="wb-btn" onClick={onCancel}>Annuler</button>
      </div>
    </form>
  );
}

function Player({ id, canManage, onBack, onEdit }) {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["trainings", id], queryFn: () => getTraining(id) });
  const [answers, setAnswers] = useState({});
  const [result, setResult] = useState(null);
  const submit = useMutation({
    mutationFn: () => submitQuiz(id, query.data.questions.map((_, i) => answers[i])),
    onSuccess: (data) => { setResult(data); qc.invalidateQueries({ queryKey: ["trainings"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (query.isLoading) return <p className="wb-state" role="status">Chargement…</p>;
  if (query.isError) return <p className="wb-state wb-state--error" role="alert">{errorMessage(query.error)}</p>;
  const t = query.data;
  const complete = t.questions.every((_, i) => answers[i] !== undefined);
  return (
    <div className="wb-panel">
      <div className="wb-row"><button type="button" className="wb-btn" onClick={onBack}>Retour</button>{canManage && <button type="button" className="wb-btn" onClick={() => onEdit(t)}>Modifier</button>}</div>
      <h2 style={{ marginTop: 16 }}>{t.title}</h2>
      {t.sections.map((s) => <section key={s.heading}><h3>{s.heading}</h3><p className="wb-muted" style={{ whiteSpace: "pre-wrap" }}>{s.body}</p></section>)}
      {t.questions.length > 0 && (
        <form onSubmit={(e) => { e.preventDefault(); setResult(null); submit.mutate(); }}>
          <h3>Quiz (réussite à {t.pass_percent} %)</h3>
          {t.questions.map((q, i) => (
            <fieldset key={i} className="wb-question">
              <legend>{i + 1}. {q.text}</legend>
              {q.options.map((opt, k) => (
                <label key={k} className="wb-option">
                  <input type="radio" name={`q${i}`} checked={answers[i] === k} onChange={() => setAnswers({ ...answers, [i]: k })} /> {opt}
                </label>
              ))}
              {result && <p className={result.results[i].correct ? "wb-result-ok" : "wb-result-ko"}>{result.results[i].correct ? "Bonne réponse." : "Pas tout à fait."} {result.results[i].explanation}</p>}
            </fieldset>
          ))}
          <div className="wb-row">
            <button type="submit" className="wb-btn wb-btn--primary" disabled={!complete || submit.isPending}>Valider mes réponses</button>
            {result && <strong role="status">{result.score}/{result.total} · {result.passed ? "Formation validée !" : "Réessaie, tu y es presque."}</strong>}
          </div>
        </form>
      )}
    </div>
  );
}

function Progress() {
  const query = useQuery({ queryKey: ["trainings", "progress"], queryFn: trainingProgress });
  if (query.isLoading) return <p className="wb-state" role="status">Chargement…</p>;
  if (query.isError) return <p className="wb-state wb-state--error" role="alert">{errorMessage(query.error)}</p>;
  const { modules, members } = query.data;
  if (!modules.length) return <p className="wb-state">Aucune formation publiée.</p>;
  return (
    <div className="wb-panel wb-table-wrap">
      <table className="wb-table">
        <caption className="wb-muted" style={{ textAlign: "left", paddingBottom: 8 }}>Complétion par membre</caption>
        <thead><tr><th scope="col">Membre</th>{modules.map((m) => <th key={m.id} scope="col">{m.title}</th>)}</tr></thead>
        <tbody>
          {members.map((r) => (
            <tr key={r.user_id}>
              <th scope="row">{r.name}</th>
              {modules.map((m) => <td key={m.id}>{r.completed.includes(m.id) ? <span className="wb-pill wb-pill--ok">Fait</span> : <span className="wb-pill">À faire</span>}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function TrainingsPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState("modules");
  const [openId, setOpenId] = useState(null);
  const [editor, setEditor] = useState(null);
  const query = useQuery({ queryKey: ["trainings", "list"], queryFn: listTrainings });
  const canManage = Boolean(query.data?.can_manage);
  const remove = useMutation({
    mutationFn: deleteTraining,
    onSuccess: () => { toast.success("Formation supprimée."); qc.invalidateQueries({ queryKey: ["trainings"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const done = () => { setEditor(null); qc.invalidateQueries({ queryKey: ["trainings"] }); };

  let body;
  if (editor) body = <div className="wb-panel"><Editor id={editor.id} initial={editor.data} onDone={done} onCancel={() => setEditor(null)} /></div>;
  else if (openId) body = <Player id={openId} canManage={canManage} onBack={() => setOpenId(null)} onEdit={(t) => setEditor({ id: t.id, data: { title: t.title, summary: t.summary, duration_min: t.duration_min, pass_percent: t.pass_percent, published: t.published, sections: t.sections, questions: t.questions.map(({ text, options, correct, explanation }) => ({ text, options, correct, explanation })) } })} />;
  else if (tab === "progress" && canManage) body = <Progress />;
  else body = (
    <>
      {query.isLoading && <p className="wb-state" role="status">Chargement…</p>}
      {query.isError && <p className="wb-state wb-state--error" role="alert">{errorMessage(query.error)}</p>}
      {query.data && query.data.items.length === 0 && <p className="wb-state">Aucune formation pour le moment.</p>}
      <ul className="wb-cards">
        {(query.data?.items ?? []).map((t) => (
          <li key={t.id} className="wb-card">
            <div className="wb-row">
              {t.completed ? <span className="wb-pill wb-pill--ok">Validée</span> : t.outdated ? <span className="wb-pill wb-pill--warn">Mise à jour</span> : <span className="wb-pill">À faire</span>}
              {!t.published && <span className="wb-pill wb-pill--warn">Brouillon</span>}
              <span className="wb-pill">{t.duration_min} min</span>
            </div>
            <h3>{t.title}</h3>
            <p className="wb-muted">{t.summary}</p>
            <div className="wb-row">
              <button type="button" className="wb-btn wb-btn--primary" onClick={() => setOpenId(t.id)}>{t.completed ? "Revoir" : "Commencer"}</button>
              {canManage && <button type="button" className="wb-btn wb-btn--danger" onClick={() => { if (window.confirm("Supprimer cette formation et son suivi ?")) remove.mutate(t.id); }}>Supprimer</button>}
            </div>
          </li>
        ))}
      </ul>
    </>
  );

  return (
    <WellbeingShell eyebrow="ESPACE ÉQUIPE · FORMATION" title="Mini-formations" testId="trainings-page"
      intro="Des modules courts avec un quiz pour se former en quelques minutes."
      actions={canManage && !editor && <button type="button" className="wb-btn wb-btn--primary" onClick={() => { setOpenId(null); setEditor({ id: null, data: blank() }); }}>Nouvelle formation</button>}>
      {canManage && !editor && !openId && (
        <div className="wb-tabs" role="tablist" aria-label="Vue">
          <button type="button" role="tab" className="wb-tab" aria-selected={tab === "modules"} onClick={() => setTab("modules")}>Formations</button>
          <button type="button" role="tab" className="wb-tab" aria-selected={tab === "progress"} onClick={() => setTab("progress")}>Suivi de l’équipe</button>
        </div>
      )}
      {body}
    </WellbeingShell>
  );
}
