import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Phone } from "lucide-react";
import WellbeingShell from "../components/wellbeing/WellbeingShell";
import { errorMessage, listSheets, resetSheet, saveSheet } from "../components/wellbeing/wellbeingApi";
import { getMe } from "../components/wellbeing/useCanManage";

const telHref = (phone) => `tel:${String(phone).replace(/[^\d+]/g, "")}`;
const toLines = (text) => text.split("\n").map((l) => l.trim()).filter(Boolean);

function SheetView({ sheet }) {
  return (
    <article aria-label={sheet.title}>
      <h2>{sheet.title}</h2>
      {sheet.summary && <p className="wb-muted">{sheet.summary}</p>}
      <h3>Que faire</h3>
      <ol className="wb-steps">{sheet.steps.map((s) => <li key={s}>{s}</li>)}</ol>
      {sheet.do_not.length > 0 && (<><h3>À éviter</h3><ul className="wb-donts">{sheet.do_not.map((s) => <li key={s}>{s}</li>)}</ul></>)}
      {sheet.resources.length > 0 && (
        <>
          <h3>Numéros utiles</h3>
          <ul className="wb-resources" aria-label="Numéros utiles">
            {sheet.resources.map((r) => (
              <li key={`${r.phone}-${r.label}`} className="wb-row">
                <a className="wb-phone" href={telHref(r.phone)}><Phone size={14} aria-hidden="true" /> {r.phone}</a>
                <span>{r.label}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </article>
  );
}

function SheetEditor({ sheet, onSaved, onCancel }) {
  const [title, setTitle] = useState(sheet.title);
  const [summary, setSummary] = useState(sheet.summary);
  const [steps, setSteps] = useState(sheet.steps.join("\n"));
  const [doNot, setDoNot] = useState(sheet.do_not.join("\n"));
  const [resources, setResources] = useState(sheet.resources.map((r) => `${r.phone} | ${r.label}`).join("\n"));
  const save = useMutation({
    mutationFn: () => saveSheet(sheet.slug, {
      title, summary, icon: sheet.icon || "", steps: toLines(steps), do_not: toLines(doNot),
      resources: toLines(resources).map((line) => {
        const [phone, ...rest] = line.split("|");
        return { phone: phone.trim(), label: rest.join("|").trim() || phone.trim() };
      }),
    }),
    onSuccess: (data) => { toast.success("Fiche enregistrée."); onSaved(data); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <form className="wb-editor" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <label className="wb-stack"><span className="wb-label">Titre</span><input className="wb-input" maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} required /></label>
      <label className="wb-stack"><span className="wb-label">Résumé</span><textarea className="wb-textarea" maxLength={400} rows={2} value={summary} onChange={(e) => setSummary(e.target.value)} /></label>
      <label className="wb-stack"><span className="wb-label">Étapes (une par ligne)</span><textarea className="wb-textarea" rows={7} value={steps} onChange={(e) => setSteps(e.target.value)} required /></label>
      <label className="wb-stack"><span className="wb-label">À éviter (une par ligne)</span><textarea className="wb-textarea" rows={3} value={doNot} onChange={(e) => setDoNot(e.target.value)} /></label>
      <label className="wb-stack"><span className="wb-label">Numéros (« numéro | libellé », un par ligne)</span><textarea className="wb-textarea" rows={4} value={resources} onChange={(e) => setResources(e.target.value)} /></label>
      <div className="wb-row">
        <button type="submit" className="wb-btn wb-btn--primary" disabled={save.isPending}>Enregistrer</button>
        <button type="button" className="wb-btn" onClick={onCancel}>Annuler</button>
      </div>
    </form>
  );
}

export default function ReflexSheetsPage() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [editing, setEditing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newSlug, setNewSlug] = useState("");
  const query = useQuery({ queryKey: ["reflex-sheets"], queryFn: listSheets });
  const me = useQuery({ queryKey: ["wellbeing", "can-manage"], queryFn: getMe, staleTime: 300000 });
  const items = useMemo(() => query.data?.items ?? [], [query.data]);
  const selected = items.find((s) => s.slug === params.get("fiche")) || items[0];
  const canManage = Boolean(me.data);
  useEffect(() => { setEditing(false); }, [selected?.slug]);

  const refresh = () => qc.invalidateQueries({ queryKey: ["reflex-sheets"] });
  const reset = useMutation({
    mutationFn: () => resetSheet(selected.slug),
    onSuccess: () => { toast.success(selected.builtin ? "Contenu d’origine rétabli." : "Fiche supprimée."); refresh(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const select = (slug) => setParams({ fiche: slug });
  const draft = { slug: newSlug, title: "", summary: "", icon: "", steps: [], do_not: [], resources: [] };

  return (
    <WellbeingShell eyebrow="ESPACE ÉQUIPE · SITUATIONS SENSIBLES" title="Fiches réflexes" testId="reflex-sheets-page"
      intro="Les bons réflexes en un coup d’œil. En danger immédiat, appelle le 15 ou le 112 sans attendre.">
      {query.isLoading && <p className="wb-state" role="status">Chargement…</p>}
      {query.isError && <p className="wb-state wb-state--error" role="alert">{errorMessage(query.error)}</p>}
      {selected && (
        <div className="wb-grid">
          <nav className="wb-panel" aria-label="Fiches">
            <ul className="wb-sheet-list">
              {items.map((s) => (
                <li key={s.slug}>
                  <button type="button" className="wb-sheet-btn" aria-current={s.slug === selected.slug} onClick={() => { setCreating(false); select(s.slug); }}>{s.title}</button>
                </li>
              ))}
            </ul>
            {canManage && (
              <div className="wb-stack" style={{ marginTop: 14 }}>
                <button type="button" className="wb-btn" onClick={() => setCreating((v) => !v)}>Nouvelle fiche</button>
                {creating && (
                  <div className="wb-subcard">
                    <label className="wb-stack"><span className="wb-label">Identifiant (minuscules, tirets)</span>
                      <input className="wb-input" value={newSlug} maxLength={40} onChange={(e) => setNewSlug(e.target.value.toLowerCase())} /></label>
                  </div>
                )}
              </div>
            )}
          </nav>
          <div className="wb-panel">
            {creating
              ? (/^[a-z0-9][a-z0-9-]{2,39}$/.test(newSlug)
                  ? <SheetEditor key={newSlug} sheet={draft} onCancel={() => setCreating(false)} onSaved={(d) => { setCreating(false); setNewSlug(""); refresh(); select(d.slug); }} />
                  : <p className="wb-muted">Saisis un identifiant valide (3 à 40 caractères : a-z, 0-9, tirets).</p>)
              : editing
                ? <SheetEditor sheet={selected} onCancel={() => setEditing(false)} onSaved={() => { setEditing(false); refresh(); }} />
                : (<>
                    <SheetView sheet={selected} />
                    {canManage && (
                      <div className="wb-row" style={{ marginTop: 18 }}>
                        <button type="button" className="wb-btn" onClick={() => setEditing(true)}>Modifier</button>
                        {(selected.customized || !selected.builtin) && (
                          <button type="button" className="wb-btn wb-btn--danger" disabled={reset.isPending} onClick={() => reset.mutate()}>
                            {selected.builtin ? "Rétablir l’original" : "Supprimer"}
                          </button>
                        )}
                      </div>
                    )}
                  </>)}
          </div>
        </div>
      )}
    </WellbeingShell>
  );
}
