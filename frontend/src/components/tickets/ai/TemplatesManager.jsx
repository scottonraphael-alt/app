import { useEffect, useRef, useState } from "react";
import { Pencil, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { api, getErrorMessage } from "../../../api/client";
import "./ai.css";

const EMPTY = { id: null, title: "", body: "", shortcut: "", scope: "personal" };

export default function TemplatesManager({ templates, canShare, helperId, onClose, onChanged }) {
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const dialogRef = useRef(null);

  useEffect(() => {
    dialogRef.current?.querySelector("input")?.focus();
    const onKey = (event) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const editable = (item) => (item.scope === "shared" ? canShare : item.owner_id === helperId || !helperId);
  const set = (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.value }));

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    const shortcut = form.shortcut.trim();
    const payload = { title: form.title.trim(), body: form.body.trim(), shortcut: shortcut ? (shortcut.startsWith("/") ? shortcut : `/${shortcut}`) : null };
    try {
      if (form.id) await api.patch(`/reply-templates/${form.id}`, payload);
      else await api.post("/reply-templates", { ...payload, scope: form.scope });
      toast.success(form.id ? "Modèle mis à jour." : "Modèle créé.");
      setForm(EMPTY);
      onChanged?.();
    } catch (requestError) {
      toast.error(getErrorMessage(requestError));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (item) => {
    if (!window.confirm(`Supprimer le modèle « ${item.title} » ?`)) return;
    try {
      await api.delete(`/reply-templates/${item.id}`);
      toast.success("Modèle supprimé.");
      if (form.id === item.id) setForm(EMPTY);
      onChanged?.();
    } catch (requestError) {
      toast.error(getErrorMessage(requestError));
    }
  };

  return (
    <div className="tai-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="tai-modal" role="dialog" aria-modal="true" aria-labelledby="tai-tpl-title" ref={dialogRef} data-testid="templates-dialog">
        <header className="tai-modal-head">
          <h2 id="tai-tpl-title">Modèles de réponse</h2>
          <button type="button" className="tai-icon-btn" onClick={onClose} aria-label="Fermer"><X size={18} /></button>
        </header>
        <form className="tai-form" onSubmit={submit}>
          <label className="tai-label" htmlFor="tai-tpl-name">Titre</label>
          <input id="tai-tpl-name" className="tai-input" required maxLength={80} value={form.title} onChange={set("title")} />
          <label className="tai-label" htmlFor="tai-tpl-short">Raccourci (facultatif, ex. /bienvenue)</label>
          <input id="tai-tpl-short" className="tai-input" maxLength={25} value={form.shortcut} onChange={set("shortcut")} />
          <label className="tai-label" htmlFor="tai-tpl-body">Texte ({"{pseudo}"} et {"{helper}"} sont remplacés)</label>
          <textarea id="tai-tpl-body" className="tai-textarea" required rows={4} maxLength={4000} value={form.body} onChange={set("body")} />
          {!form.id && canShare && (
            <>
              <label className="tai-label" htmlFor="tai-tpl-scope">Visibilité</label>
              <select id="tai-tpl-scope" className="tai-select" value={form.scope} onChange={set("scope")}>
                <option value="personal">Personnel</option>
                <option value="shared">Partagé avec l’équipe</option>
              </select>
            </>
          )}
          <div className="tai-row">
            <button type="submit" className="tai-btn tai-btn-solid" disabled={saving}>{form.id ? "Enregistrer" : "Créer le modèle"}</button>
            {form.id && <button type="button" className="tai-btn" onClick={() => setForm(EMPTY)}>Annuler la modification</button>}
          </div>
        </form>
        <ul className="tai-tpl-list" aria-label="Modèles existants">
          {templates.length === 0 && <li className="tai-note">Aucun modèle pour l’instant.</li>}
          {templates.map((item) => (
            <li key={item.id}>
              <div>
                <strong>{item.title}</strong>
                <span className="tai-note">{item.shortcut ? ` ${item.shortcut}` : ""} · {item.scope === "shared" ? "partagé" : "personnel"}</span>
              </div>
              {editable(item) && (
                <div className="tai-row">
                  <button type="button" className="tai-icon-btn" aria-label={`Modifier ${item.title}`} onClick={() => setForm({ id: item.id, title: item.title, body: item.body, shortcut: item.shortcut || "", scope: item.scope })}><Pencil size={15} /></button>
                  <button type="button" className="tai-icon-btn" aria-label={`Supprimer ${item.title}`} onClick={() => remove(item)}><Trash2 size={15} /></button>
                </div>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
