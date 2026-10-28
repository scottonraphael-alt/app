import { useCallback, useEffect, useState } from "react";
import { BellRing, StickyNote, Tag, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import {
  FOLLOWUP_PRESETS, TAG_COLORS, addNote, cancelFollowup, createFollowup, createTag, deleteNote, deleteTag,
  errorMessage, fetchFollowups, fetchNotes, fetchTags, fetchTagAssignments, setTicketTags,
} from "./extrasApi";
import "./extras.css";

const fmt = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "");

export default function TicketExtrasPanel({ ticketId, isAdmin = false, helperId }) {
  const [notes, setNotes] = useState([]);
  const [draft, setDraft] = useState("");
  const [tags, setTags] = useState([]);
  const [mine, setMine] = useState([]);
  const [newTag, setNewTag] = useState("");
  const [newColor, setNewColor] = useState("sauge");
  const [followups, setFollowups] = useState([]);
  const [followNote, setFollowNote] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [n, t, a, f] = await Promise.allSettled([fetchNotes(ticketId), fetchTags(), fetchTagAssignments(), fetchFollowups(ticketId)]);
    if (n.status === "fulfilled") setNotes(Array.isArray(n.value) ? n.value : []);
    if (t.status === "fulfilled") setTags(Array.isArray(t.value) ? t.value : []);
    if (a.status === "fulfilled") setMine(a.value?.[ticketId] || []);
    if (f.status === "fulfilled") setFollowups(Array.isArray(f.value) ? f.value : []);
  }, [ticketId]);
  useEffect(() => { load(); }, [load]);

  const run = async (fn, ok) => {
    setBusy(true);
    try { await fn(); if (ok) toast.success(ok); } catch (err) { toast.error(errorMessage(err)); } finally { setBusy(false); }
  };

  const submitNote = (event) => {
    event.preventDefault();
    if (!draft.trim()) return;
    run(async () => { const n = await addNote(ticketId, draft.trim()); setNotes((c) => [n, ...c]); setDraft(""); }, "Note interne ajoutée.");
  };
  const toggleTag = (id) => {
    const next = mine.includes(id) ? mine.filter((x) => x !== id) : [...mine, id];
    run(async () => { const r = await setTicketTags(ticketId, next); setMine(r.tag_ids); });
  };
  const submitTag = (event) => {
    event.preventDefault();
    if (!newTag.trim()) return;
    run(async () => { const t = await createTag(newTag.trim(), newColor); setTags((c) => [...c, t]); setNewTag(""); }, "Étiquette créée.");
  };
  const remindMe = (preset) => run(async () => {
    const f = await createFollowup(ticketId, preset, followNote.trim());
    setFollowups((c) => [...c, f].sort((a, b) => a.due_at.localeCompare(b.due_at)));
    setFollowNote("");
  }, "Rappel programmé.");

  return (
    <div className="tx-panel" data-testid="ticket-extras">
      <section className="tx-block" aria-labelledby="tx-notes-title">
        <h3 id="tx-notes-title"><StickyNote size={15} aria-hidden="true" /> Notes internes</h3>
        <p className="tx-hint">Visibles des helpers uniquement, jamais envoyées au membre.</p>
        <form onSubmit={submitNote} className="tx-form">
          <label className="tx-sr" htmlFor="tx-note">Nouvelle note interne</label>
          <textarea id="tx-note" className="tx-input" rows={3} maxLength={4000} value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Une information pour l'équipe…" />
          <button type="submit" className="tx-btn tx-btn-solid" disabled={busy || !draft.trim()}>Ajouter</button>
        </form>
        <ul className="tx-list">
          {notes.map((n) => (
            <li key={n.id} className="tx-item">
              <p className="tx-text">{n.body}</p>
              <div className="tx-meta"><span>{n.author_name} · {fmt(n.created_at)}</span>
                {(isAdmin || n.author_id === helperId) && (
                  <button type="button" className="tx-icon" aria-label="Supprimer la note interne" onClick={() => run(async () => { await deleteNote(ticketId, n.id); setNotes((c) => c.filter((x) => x.id !== n.id)); })}><Trash2 size={13} /></button>)}
              </div>
            </li>))}
          {!notes.length && <li className="tx-empty">Aucune note interne.</li>}
        </ul>
      </section>

      <section className="tx-block" aria-labelledby="tx-tags-title">
        <h3 id="tx-tags-title"><Tag size={15} aria-hidden="true" /> Étiquettes</h3>
        <div className="tx-chips">
          {tags.map((t) => (
            <span key={t.id} className="tx-chipwrap">
              <button type="button" className={`tx-chip tx-c-${t.color}${mine.includes(t.id) ? " is-on" : ""}`} aria-pressed={mine.includes(t.id)} disabled={busy} onClick={() => toggleTag(t.id)}>{t.name}</button>
              {isAdmin && <button type="button" className="tx-icon" aria-label={`Supprimer l'étiquette ${t.name}`} onClick={() => run(async () => { await deleteTag(t.id); setTags((c) => c.filter((x) => x.id !== t.id)); setMine((c) => c.filter((x) => x !== t.id)); })}><X size={12} /></button>}
            </span>))}
          {!tags.length && <span className="tx-empty">Aucune étiquette définie.</span>}
        </div>
        {isAdmin && (
          <form onSubmit={submitTag} className="tx-row">
            <label className="tx-sr" htmlFor="tx-newtag">Nom de l'étiquette</label>
            <input id="tx-newtag" className="tx-input" maxLength={30} value={newTag} onChange={(e) => setNewTag(e.target.value)} placeholder="Nouvelle étiquette" />
            <label className="tx-sr" htmlFor="tx-newcolor">Couleur</label>
            <select id="tx-newcolor" className="tx-input tx-select" value={newColor} onChange={(e) => setNewColor(e.target.value)}>{TAG_COLORS.map((c) => <option key={c} value={c}>{c}</option>)}</select>
            <button type="submit" className="tx-btn" disabled={busy || !newTag.trim()}>Créer</button>
          </form>)}
      </section>

      <section className="tx-block" aria-labelledby="tx-fu-title">
        <h3 id="tx-fu-title"><BellRing size={15} aria-hidden="true" /> Me rappeler</h3>
        <label className="tx-sr" htmlFor="tx-funote">Mémo du rappel</label>
        <input id="tx-funote" className="tx-input" maxLength={200} value={followNote} onChange={(e) => setFollowNote(e.target.value)} placeholder="Mémo (facultatif)" />
        <div className="tx-row">
          {FOLLOWUP_PRESETS.map((p) => <button key={p.value} type="button" className="tx-btn" disabled={busy} onClick={() => remindMe(p.value)}>{p.label}</button>)}
        </div>
        <ul className="tx-list">
          {followups.map((f) => (
            <li key={f.id} className="tx-item tx-meta"><span>Rappel le {fmt(f.due_at)}{f.note ? ` · ${f.note}` : ""}</span>
              <button type="button" className="tx-icon" aria-label="Annuler le rappel" onClick={() => run(async () => { await cancelFollowup(f.id); setFollowups((c) => c.filter((x) => x.id !== f.id)); })}><X size={13} /></button></li>))}
        </ul>
      </section>
    </div>
  );
}
