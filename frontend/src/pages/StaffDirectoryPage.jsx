import "../Team.css";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import Avatar from "../components/team/Avatar";
import TeamHeader from "../components/team/TeamHeader";
import {
  DAYS, STATES, errorMessage, fetchDirectory, fetchMyCard, saveMyCard, teamKeys,
} from "../components/team/teamApi";

function CardEditor({ onClose }) {
  const qc = useQueryClient();
  const card = useQuery({ queryKey: teamKeys.card, queryFn: fetchMyCard });
  const [form, setForm] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (card.data && !form) {
      setForm({
        pronouns: card.data.pronouns, bio: card.data.bio,
        skills: card.data.skills.join(", "), availability: card.data.availability,
      });
    }
  }, [card.data, form]);

  const save = useMutation({
    mutationFn: () => saveMyCard({
      pronouns: form.pronouns, bio: form.bio, availability: form.availability,
      skills: form.skills.split(",").map((s) => s.trim()).filter(Boolean),
    }),
    onSuccess: () => {
      toast.success("Fiche enregistrée.");
      qc.invalidateQueries({ queryKey: ["team", "directory"] });
      qc.invalidateQueries({ queryKey: teamKeys.card });
      onClose();
    },
    onError: (err) => setError(errorMessage(err)),
  });

  if (!form) return <section className="tm-panel"><p className="tm-state" role="status">Chargement…</p></section>;
  const setSlot = (i, patch) => setForm({ ...form, availability: form.availability.map((s, j) => (j === i ? { ...s, ...patch } : s)) });

  return (
    <section className="tm-panel" aria-label="Modifier ma fiche">
      <h2>Ma fiche</h2>
      <form className="tm-form" onSubmit={(e) => { e.preventDefault(); setError(""); save.mutate(); }}>
        <label className="tm-label" htmlFor="tm-pronouns">Pronoms (facultatif)</label>
        <input id="tm-pronouns" className="tm-input" maxLength={24} value={form.pronouns}
          onChange={(e) => setForm({ ...form, pronouns: e.target.value })} />
        <label className="tm-label" htmlFor="tm-bio">Présentation courte ({form.bio.length}/280)</label>
        <textarea id="tm-bio" className="tm-input tm-textarea" maxLength={280} value={form.bio}
          onChange={(e) => setForm({ ...form, bio: e.target.value })} />
        <label className="tm-label" htmlFor="tm-skills">Compétences (séparées par des virgules, 10 max)</label>
        <input id="tm-skills" className="tm-input" value={form.skills}
          onChange={(e) => setForm({ ...form, skills: e.target.value })} />
        <fieldset className="tm-fieldset">
          <legend className="tm-label">Disponibilités habituelles</legend>
          {form.availability.map((s, i) => (
            <div className="tm-slot" key={i}>
              <select className="tm-input" aria-label="Jour" value={s.day} onChange={(e) => setSlot(i, { day: Number(e.target.value) })}>
                {DAYS.map((d, n) => <option key={d} value={n}>{d}</option>)}
              </select>
              <input className="tm-input" type="time" aria-label="Début" value={s.start} onChange={(e) => setSlot(i, { start: e.target.value })} />
              <input className="tm-input" type="time" aria-label="Fin" value={s.end} onChange={(e) => setSlot(i, { end: e.target.value })} />
              <button type="button" className="tm-btn" onClick={() => setForm({ ...form, availability: form.availability.filter((_, j) => j !== i) })}>Retirer</button>
            </div>
          ))}
          {form.availability.length < 14 && (
            <button type="button" className="tm-btn" onClick={() => setForm({ ...form, availability: [...form.availability, { day: 0, start: "18:00", end: "22:00" }] })}>
              Ajouter un créneau
            </button>
          )}
        </fieldset>
        {error && <p className="tm-error" role="alert">{error}</p>}
        <div className="tm-actions">
          <button type="submit" className="tm-btn tm-btn--primary" disabled={save.isPending}>Enregistrer</button>
          <button type="button" className="tm-btn" onClick={onClose}>Annuler</button>
        </div>
      </form>
    </section>
  );
}

function MemberCard({ m }) {
  return (
    <li className="tm-card">
      <div className="tm-card-head">
        <Avatar name={m.name} url={m.avatar_url} />
        <div className="tm-card-id">
          <h3>{m.name}{m.pronouns && <span className="tm-pronouns"> · {m.pronouns}</span>}</h3>
          <p className="tm-status-line">
            <span className={`tm-dot tm-dot--${m.status.state}`} aria-hidden="true" />
            {m.status.label}{m.status.message ? ` — ${m.status.message}` : ""}
          </p>
        </div>
      </div>
      <div className="tm-chips">{m.roles.map((r) => <span className="tm-chip" key={r.key}>{r.label}</span>)}</div>
      {m.bio && <p className="tm-bio">{m.bio}</p>}
      {m.skills.length > 0 && (
        <ul className="tm-chips" aria-label="Compétences">{m.skills.map((s) => <li className="tm-chip tm-chip--soft" key={s}>{s}</li>)}</ul>
      )}
      {m.availability.length > 0 && (
        <ul className="tm-avail" aria-label="Disponibilités habituelles">
          {m.availability.map((s, i) => <li key={i}>{DAYS[s.day]} · {s.start}–{s.end}</li>)}
        </ul>
      )}
    </li>
  );
}

export default function StaffDirectoryPage() {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [role, setRole] = useState("");
  const [state, setState] = useState("");
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);

  const params = { ...(debounced ? { q: debounced } : {}), ...(role ? { role } : {}), ...(state ? { state } : {}) };
  const query = useQuery({ queryKey: teamKeys.directory(params), queryFn: () => fetchDirectory(params), keepPreviousData: true });
  const items = query.data?.items ?? [];
  const roles = query.data?.roles ?? [];

  return (
    <section className="tm-page" data-testid="staff-directory-page">
      <TeamHeader eyebrow="ESPACE STAFF · ÉQUIPE" title="Annuaire du staff"
        intro="Qui fait quoi, quand et comment les joindre." />
      <div className="tm-toolbar">
        <label className="tm-search">
          <span className="tm-sr">Rechercher un membre</span>
          <input className="tm-input" type="search" placeholder="Nom, compétence, présentation…" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <label>
          <span className="tm-sr">Filtrer par rôle</span>
          <select className="tm-input" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="">Tous les rôles</option>
            {roles.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
          </select>
        </label>
        <label>
          <span className="tm-sr">Filtrer par statut</span>
          <select className="tm-input" value={state} onChange={(e) => setState(e.target.value)}>
            <option value="">Tous les statuts</option>
            {STATES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        </label>
        <button type="button" className="tm-btn tm-btn--primary" onClick={() => setEditing((v) => !v)}>
          {editing ? "Fermer ma fiche" : "Modifier ma fiche"}
        </button>
      </div>
      {editing && <CardEditor onClose={() => setEditing(false)} />}
      {query.isLoading && <p className="tm-state" role="status">Chargement…</p>}
      {query.isError && (
        <div className="tm-state tm-state--error" role="alert">
          {errorMessage(query.error)} <button type="button" className="tm-btn" onClick={() => query.refetch()}>Réessayer</button>
        </div>
      )}
      {!query.isLoading && !query.isError && items.length === 0 && <p className="tm-state">Aucun membre ne correspond.</p>}
      <ul className="tm-grid" aria-live="polite">{items.map((m) => <MemberCard key={m.id} m={m} />)}</ul>
    </section>
  );
}
